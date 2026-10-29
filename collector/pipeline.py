"""Конвейер: поиск → загрузка сайтов → извлечение моделью → проверка → карточки.

Запуск полного сбора:   python -m collector.pipeline
Один запрос (как в живом поиске):  python -m collector.pipeline --query "нори оптом" --city Екатеринбург
"""
import argparse
import asyncio
import json
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import httpx

from .config import CANDIDATES_PER_CATEGORY_REGION, CATEGORIES, REGIONS, SEARCH_RESULTS_PER_QUERY
from .extract import LLMUnavailable, extract
from .fetch import fetch_site
from .search import domain_of, is_blocked, search
from .verify import check_fact, verify

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "suppliers.json"
WEB_OUT = ROOT / "web" / "data" / "suppliers.json"


def save_db(db: dict) -> None:
    """Атомарная запись: читатели никогда не увидят наполовину записанный JSON."""
    import os
    body = json.dumps(db, ensure_ascii=False, indent=1)
    for path in (OUT, WEB_OUT):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(body, "utf-8")
        os.replace(tmp, path)


async def discover(client, queries: list[str], limit: int, log) -> list[dict]:
    found, seen = [], set()
    for q in queries:
        for r in await search(client, q, SEARCH_RESULTS_PER_QUERY):
            d = domain_of(r["url"])
            if not d or d in seen or is_blocked(d):
                continue
            seen.add(d)
            found.append({"domain": d, "url": f"https://{urlhost(r['url'])}/", "query": q})
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break
    log(f"  «{queries[0]}…»: {len(found)} сайтов")
    return found


def urlhost(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).hostname


async def process_site(client, cand: dict, requested: str, sem, stats: Counter, rejects: Counter):
    async with sem:
        try:  # общий таймаут: сайт, который держит соединение, не должен вешать весь сбор
            site = await asyncio.wait_for(fetch_site(client, cand["url"]), timeout=90)
        except asyncio.TimeoutError:
            site = None
        if not site:
            stats["сайт не открылся"] += 1
            return None
        try:
            ex = await asyncio.wait_for(extract(client, site, requested), timeout=240)
        except (LLMUnavailable, asyncio.TimeoutError):
            stats["модель недоступна"] += 1
            return None
        stats["cost"] += ex.get("cost") or 0
        card, rejected = verify(site, ex["result"])
        for r in rejected:
            rejects[r["reason"]] += 1
        if not card:
            stats["отсеяно проверкой"] += 1
            return None
        sells = check_fact({"value": "да" if ex["result"]["sells_requested"]["value"] else None,
                            "evidence": ex["result"]["sells_requested"]["evidence"],
                            "page": ex["result"]["sells_requested"]["page"]}, site["pages"], "sells")[0]
        card["requested_match"] = sells
        card["checked_at"] = date.today().isoformat()
        card["found_by"] = cand["query"]
        stats["карточек"] += 1
        return card


async def run_full(log=print) -> dict:
    t0 = time.time()
    stats, rejects = Counter(), Counter()
    async with httpx.AsyncClient(http2=False, limits=httpx.Limits(max_connections=20)) as client:
        by_domain: dict[str, dict] = {}
        wanted = defaultdict(set)
        dsem = asyncio.Semaphore(5)

        async def disc(cat, reg):
            async with dsem:
                queries = [f"{q} {reg['name']}" for q in cat["queries"]]
                try:
                    return cat, await asyncio.wait_for(
                        discover(client, queries, CANDIDATES_PER_CATEGORY_REGION, log), timeout=300)
                except asyncio.TimeoutError:
                    return cat, []
        for cat, found in await asyncio.gather(*[disc(c, r) for c in CATEGORIES for r in REGIONS]):
            for c in found:
                by_domain.setdefault(c["domain"], c)
                wanted[c["domain"]].add(cat["name"])
        stats["кандидатов"] = len(by_domain)
        log(f"Кандидатов: {len(by_domain)}")
        sem = asyncio.Semaphore(8)
        tasks = [process_site(client, c, "; ".join(sorted(wanted[d])), sem, stats, rejects)
                 for d, c in by_domain.items()]
        cards = [c for c in await asyncio.gather(*tasks) if c]
    cards.sort(key=lambda c: c["name"].lower())
    result = {
        "generated_at": date.today().isoformat(),
        "categories": [{"id": c["id"], "name": c["name"]} for c in CATEGORIES],
        "regions": [{"id": r["id"], "name": r["name"]} for r in REGIONS],
        "stats": {"candidates": stats["кандидатов"], "suppliers": len(cards),
                  "site_failed": stats["сайт не открылся"], "rejected_by_check": stats["отсеяно проверкой"],
                  "llm_failed": stats["модель недоступна"],
                  "facts_rejected": dict(rejects.most_common()),
                  "llm_cost_usd": round(stats["cost"], 3), "seconds": round(time.time() - t0)},
        "suppliers": cards,
    }
    save_db(result)
    log(json.dumps(result["stats"], ensure_ascii=False))
    return result


async def run_query(query: str, city: str, limit: int = 8, log=print, client=None, on_card=None) -> list[dict]:
    """Живой поиск по произвольному запросу: то же самое, но для одного запроса."""
    own = client is None
    client = client or httpx.AsyncClient(limits=httpx.Limits(max_connections=20))
    try:
        stats, rejects = Counter(), Counter()
        cands = await discover(client, [f"{query} оптом {city}", f"{query} поставщик {city}"], limit, log)
        log(f"Нашёл сайтов: {len(cands)}")
        sem = asyncio.Semaphore(6)
        cards = []
        for coro in asyncio.as_completed([process_site(client, c, query, sem, stats, rejects) for c in cands]):
            card = await coro
            if card and card.get("requested_match"):
                cards.append(card)
                if on_card:
                    on_card(card)
                else:
                    log(f"Подтверждён: {card['name']}")
        return cards
    finally:
        if own:
            await client.aclose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--query")
    ap.add_argument("--city", default="Екатеринбург")
    a = ap.parse_args()
    if a.query:
        res = asyncio.run(run_query(a.query, a.city))
        print(json.dumps(res, ensure_ascii=False, indent=1)[:6000])
    else:
        asyncio.run(run_full())
