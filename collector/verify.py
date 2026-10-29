"""Детерминированная проверка ответа модели. Здесь нет LLM: только сверка с текстом сайта.

Факт попадает в карточку, только если:
  1) цитата (evidence) дословно есть на указанной странице (после нормализации пробелов, регистра, ё/е, кавычек);
  2) значение (value) подкреплено цитатой: все числа значения есть в цитате, и большая часть слов значения тоже;
  3) поле имеет смысл (не пустое, не «по запросу» вместо цены и т.п.).
Всё остальное отбрасывается и записывается в журнал отказов с причиной.
"""
import re

from .config import CATEGORY_IDS, REGIONS

QUOTES = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "’": "'", "‘": "'",
                        "–": "-", "—": "-", "‑": "-", "ё": "е", "Ё": "Е", " ": " "})


def norm(s: str) -> str:
    s = (s or "").translate(QUOTES).lower()
    return re.sub(r"\s+", " ", s).strip()


def stem_words(s: str) -> list[str]:
    return [w[:5] for w in re.findall(r"[a-zа-я]{4,}", norm(s))]


def numbers(s: str) -> list[str]:
    t = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", norm(s))  # «10 000» → «10000», но «5 2 дня» не склеиваем
    return re.findall(r"\d+(?:[.,]\d+)?", t)


EMPTY_VALUES = {"нет", "не указано", "не указан", "отсутствует", "n/a", "null", "-", "неизвестно"}
PRICE_WITHOUT_NUMBERS = re.compile(r"по запрос|договорн|уточн|индивидуал|звоните", re.I)


def page_text(p: dict) -> str:
    return norm(p.get("title", "") + " " + p["text"])


def find_quote(evidence: str, page: int | None, pages: list[dict]) -> str | None:
    """URL страницы, где цитата есть дословно. Сначала указанная моделью страница, потом остальные."""
    ev = norm(evidence)
    if len(ev) < 4:
        return None
    order = ([page] if isinstance(page, int) and 0 <= page < len(pages) else []) + list(range(len(pages)))
    for i in order:
        if ev in page_text(pages[i]):
            return pages[i]["url"]
    return None


def check_fact(fact: dict | None, pages: list[dict], field: str) -> tuple[dict | None, str | None]:
    """Возвращает (проверенный факт, причина отказа)."""
    if not fact or not fact.get("value"):
        return None, None
    value, evidence = fact["value"].strip(), (fact.get("evidence") or "").strip()
    if norm(value) in EMPTY_VALUES:
        return None, None
    if len(evidence) < 4:
        return None, "нет цитаты"
    url = find_quote(evidence, fact.get("page"), pages)
    if not url:
        return None, "цитаты нет на сайте"
    ev_nums = set(numbers(evidence))
    if any(n not in ev_nums for n in numbers(value)):
        return None, "в значении числа, которых нет в цитате"
    v_words = stem_words(value)
    if v_words:
        ev_stems = set(stem_words(evidence))
        hit = sum(1 for w in v_words if w in ev_stems)
        if hit / len(v_words) < 0.6:
            return None, "значение не следует из цитаты"
    if field == "price_info" and not numbers(value):
        return None, "цена без цифр"
    if field == "min_order" and not numbers(value) and PRICE_WITHOUT_NUMBERS.search(value):
        return None, "минимальный заказ без условий"
    return {"value": value[:220], "evidence": evidence[:240], "url": url}, None


INN_RE = re.compile(r"ИНН[\s:№/КПП]*?(\d{10}|\d{12})(?!\d)", re.I)


def inn_valid(inn: str) -> bool:
    """Контрольная сумма ИНН по алгоритму ФНС (10 цифр у юрлиц, 12 у ИП)."""
    d = [int(c) for c in inn]
    def ctrl(coefs):
        return sum(c * x for c, x in zip(coefs, d)) % 11 % 10
    if len(d) == 10:
        return ctrl([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    if len(d) == 12:
        return (ctrl([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10]
                and ctrl([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11])
    return False


def find_inn(pages: list[dict]) -> dict | None:
    for p in pages:
        for m in INN_RE.finditer(p["text"]):
            if inn_valid(m.group(1)):
                start = max(0, m.start() - 40)
                return {"value": m.group(1), "evidence": p["text"][start:m.end()].strip(), "url": p["url"]}
    return None


GENERIC_TITLE = re.compile(r"^(главная|главная страница|home|официальный сайт|о компании)$", re.I)


def clean_name(name: str, from_title: bool, domain: str) -> str:
    n = re.sub(r"\s+", " ", name).strip()
    n = re.sub(r"общество с ограниченной ответственностью", "ООО", n, flags=re.I)
    n = re.sub(r"индивидуальный предприниматель", "ИП", n, flags=re.I)
    n = re.sub(r"акционерное общество", "АО", n, flags=re.I)
    if from_title:  # заголовок страницы: «Главная ⋆ Покров замороженные…», «Рыба оптом | Рыбный двор»
        parts = [p.strip() for p in re.split(r"\s[|⋆•—–\-:]\s|\s?[|⋆•]\s?", n) if p.strip()]
        parts = [p for p in parts if not GENERIC_TITLE.match(p)]
        n = min(parts, key=len) if parts else n
        if len(n) > 32:
            return domain
    return n[:60]


def readable_host(domain: str) -> str:
    try:
        return domain.encode().decode("idna")
    except UnicodeError:
        return domain


def region_ids(text: str) -> list[str]:
    t = norm(text)
    ids = [r["id"] for r in REGIONS if any(a in t for a in r["aliases"])]
    if re.search(r"вс(ей|ю|я) росси|по росси|регионы росси|всем регион|рф\b|по стране", t):
        ids.append("russia")
    return ids


def verify(site: dict, extracted: dict) -> tuple[dict | None, list[dict]]:
    """Собирает карточку поставщика только из проверенных фактов."""
    pages = site["pages"]
    rejected = []
    kind = extracted.get("site_kind")
    if kind != "supplier":
        return None, [{"field": "site_kind", "reason": f"не поставщик ({kind})"}]

    facts = {}
    for field in ["company_name", "products", "city", "address", "regions_served", "min_order",
                  "price_info", "certificates", "delivery", "horeca", "founded"]:
        ok, reason = check_fact(extracted.get(field), pages, field)
        if ok:
            facts[field] = ok
        elif reason:
            rejected.append({"field": field, "reason": reason, "value": (extracted.get(field) or {}).get("value")})

    cats = []
    for c in extracted.get("categories") or []:
        if c.get("id") not in CATEGORY_IDS or c["id"] in [x["id"] for x in cats]:
            continue
        url = find_quote(c.get("evidence") or "", c.get("page"), pages)
        if url:
            cats.append({"id": c["id"], "evidence": c["evidence"].strip()[:240], "url": url})
        else:
            rejected.append({"field": f"category:{c.get('id')}", "reason": "цитаты нет на сайте"})

    if not cats:
        return None, rejected + [{"field": "categories", "reason": "нет подтверждённых категорий"}]

    contacts = {"phones": [], "emails": []}
    for p in pages:
        for k in contacts:
            for v in p.get("contacts", {}).get(k, []):
                if v not in contacts[k]:
                    contacts[k].append(v)
    contacts = {k: v[:3] for k, v in contacts.items()}
    if not contacts["phones"] and not contacts["emails"]:
        return None, rejected + [{"field": "contacts", "reason": "на сайте нет ни телефона, ни почты"}]

    raw_name = facts.get("company_name", {}).get("value")
    name = clean_name(raw_name or site.get("title") or site["domain"], not raw_name, site["domain"])
    regions_text = " ".join(facts.get(f, {}).get("value", "") for f in ("city", "address", "regions_served"))
    regions = set(region_ids(regions_text))
    for ph in contacts["phones"]:
        code = ph[3:6]
        if code == "343":
            regions.add("ekb")
        elif code in ("495", "499"):
            regions.add("msk")
    return {
        "id": site["domain"],
        "name": name,
        "site": site["home"],
        "domain": site["domain"],
        "host": readable_host(site["domain"]),
        "categories": cats,
        "regions": sorted(regions),
        "contacts": contacts,
        "inn": find_inn(pages),
        "facts": facts,
        "pages_checked": [p["url"] for p in pages],
    }, rejected
