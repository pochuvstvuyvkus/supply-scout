"""Загрузка сайта поставщика: главная и до N внутренних страниц (контакты, доставка, сертификаты...)."""
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .cache import cached_json
from .config import PAGE_TEXT_LIMIT, PAGES_PER_SITE
from .search import UA, domain_of

USEFUL_LINK = re.compile(
    r"контакт|contact|о-?компан|о нас|about|достав|delivery|оплат|услови|сертиф|certif|"
    r"документ|опт|wholesale|партн|сотруднич|horeca|хорека|ресторан|прайс|price|каталог|catalog|продукц",
    re.I)

PHONE_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s\- ]*\(?\d{3,4}\)?[\s\- ]*\d{1,3}[\s\- ]*\d{2}[\s\- ]*\d{2}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
BAD_EMAIL_TAIL = re.compile(r"\.(png|jpe?g|gif|webp|svg|css|js)$", re.I)


def decode(resp: httpx.Response) -> str:
    raw = resp.content
    enc = resp.charset_encoding
    if not enc:
        m = re.search(rb'charset=["\']?([\w\-]+)', raw[:3000], re.I)
        enc = m.group(1).decode() if m else "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def html_to_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return title, text


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return None
    if digits[1] not in "3489":  # коды городов и мобильных в РФ начинаются с 3, 4, 8, 9
        return None
    return f"+7 {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def extract_contacts(html: str, text: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    phones, emails = [], []
    for a in soup.select("a[href^='tel:']"):
        p = normalize_phone(a["href"][4:])
        if p and p not in phones:
            phones.append(p)
    for m in PHONE_RE.finditer(text):
        p = normalize_phone(m.group(0))
        if p and p not in phones:
            phones.append(p)
    for a in soup.select("a[href^='mailto:']"):
        e = a["href"][7:].split("?")[0].strip().lower()
        if EMAIL_RE.fullmatch(e) and e not in emails:
            emails.append(e)
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower().strip(".")
        if not BAD_EMAIL_TAIL.search(e) and e not in emails:
            emails.append(e)
    return {"phones": phones[:4], "emails": emails[:3]}


async def get_page(client: httpx.AsyncClient, url: str) -> dict | None:
    async def run():
        try:
            r = await client.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        except Exception as e:  # сеть, TLS, таймаут: страницы просто нет
            return {"url": url, "ok": False, "error": type(e).__name__}
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            return {"url": url, "ok": False, "error": f"HTTP {r.status_code}"}
        html = decode(r)
        title, text = html_to_text(html)
        links = []
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            label = " ".join(a.get_text(" ").split())[:80]
            links.append({"href": urljoin(str(r.url), a["href"]), "label": label})
        return {"url": str(r.url), "ok": True, "title": title, "text": text,
                "contacts": extract_contacts(html, text), "links": links[:400]}
    return await cached_json("pages", url, run)


async def fetch_site(client: httpx.AsyncClient, start_url: str) -> dict | None:
    home = await get_page(client, start_url)
    if not home or not home.get("ok"):
        return None
    site_domain = domain_of(home["url"])
    picked, seen = [], {home["url"].rstrip("/")}
    for link in home["links"]:
        href = link["href"].split("#")[0]
        if domain_of(href) != site_domain or href.rstrip("/") in seen:
            continue
        if re.search(r"\.(pdf|jpe?g|png|zip|docx?|xlsx?)$", href, re.I):
            continue
        if USEFUL_LINK.search(link["label"]) or USEFUL_LINK.search(urlparse(href).path):
            picked.append(href)
            seen.add(href.rstrip("/"))
        if len(picked) >= PAGES_PER_SITE - 1:
            break
    pages = [home]
    for href in picked:
        p = await get_page(client, href)
        if p and p.get("ok"):
            pages.append(p)
    for p in pages:
        p["text"] = p["text"][:PAGE_TEXT_LIMIT]
    return {"domain": site_domain, "home": home["url"], "title": home.get("title", ""), "pages": pages}
