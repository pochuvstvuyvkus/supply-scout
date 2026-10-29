"""Поиск кандидатов.

Основной источник: веб-поиск Exa через OpenRouter (возвращает ссылки на источники).
Запасной: HTML-выдача DuckDuckGo без ключей. Пустые выдачи не кэшируются.
"""
import asyncio
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import BLOCKED_DOMAINS
from .cache import cached_json

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_blocked(domain: str) -> bool:
    return any(domain == b or domain.endswith("." + b) for b in BLOCKED_DOMAINS)


def parse_ddg(html: str) -> list[dict]:
    out = []
    for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        if href.startswith("http"):
            out.append({"url": href, "title": title})
    return out


async def search_exa(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    from .extract import api_key
    prompt = (f"Найди сайты компаний-поставщиков по запросу: «{query}». "
              "Нужны сайты самих поставщиков и оптовых компаний, которые работают с ресторанами и кафе, "
              "а не каталоги, маркетплейсы или справочники. Перечисли компании.")
    r = await client.post("https://openrouter.ai/api/v1/chat/completions",
                          headers={"Authorization": f"Bearer {api_key()}"},
                          json={"model": "google/gemini-2.5-flash",
                                "plugins": [{"id": "web", "engine": "exa", "max_results": limit}],
                                "messages": [{"role": "user", "content": prompt}]},
                          timeout=120)
    if r.status_code != 200:
        return []
    msg = r.json().get("choices", [{}])[0].get("message", {})
    out = []
    for a in msg.get("annotations") or []:
        u = (a.get("url_citation") or {}).get("url")
        if u and u.startswith("http"):
            out.append({"url": u, "title": (a.get("url_citation") or {}).get("title", ""), "engine": "exa"})
    return out


async def search_ddg(client: httpx.AsyncClient, query: str) -> list[dict]:
    for attempt in range(2):
        r = await client.post("https://html.duckduckgo.com/html/", data={"q": query, "kl": "ru-ru"},
                              headers={"User-Agent": UA}, timeout=25)
        if r.status_code == 200 and "result__a" in r.text:
            return [dict(x, engine="ddg") for x in parse_ddg(r.text)]
        await asyncio.sleep(5 * (attempt + 1))
    return []


async def search(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    async def run():
        res = await search_exa(client, query, limit)
        if not res:
            res = await search_ddg(client, query)
        return res or None  # None не кэшируется: при следующем запуске попробуем снова
    return ((await cached_json("search", query, run)) or [])[:limit]
