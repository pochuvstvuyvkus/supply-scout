"""Независимый аудит базы: заново скачивает каждую страницу-источник (без кэша конвейера)
и проверяет, что каждая цитата, телефон и почта действительно там есть, а числа значения взяты из цитаты.

    python scripts/audit.py            → data/audit.json и сводка в консоли
Код намеренно не использует collector.verify: проверка не должна зависеть от того, что проверяет.
"""
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"


def clean(s: str) -> str:
    s = s.lower().replace("ё", "е").replace(" ", " ")
    s = re.sub(r"[«»“”„\"']", "", s)
    s = re.sub(r"[–—‑]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


async def page(client, url, memo):
    if url not in memo:
        r = None
        for attempt in range(3):  # сайты иногда отвечают ошибкой на частые запросы: повторяем с паузой
            try:
                r = await client.get(url, headers={"User-Agent": UA}, timeout=25, follow_redirects=True)
                if r.status_code < 400:
                    break
            except Exception:
                r = None
            await asyncio.sleep(3 * (attempt + 1))
        try:
            if r is None:
                raise ConnectionError("нет ответа")
            raw = r.content
            m = re.search(rb'charset=["\']?([\w\-]+)', raw[:3000], re.I)
            html = raw.decode(r.charset_encoding or (m.group(1).decode() if m else "utf-8"), errors="replace")
            soup = BeautifulSoup(html, "lxml")
            for t in soup(["script", "style", "noscript"]):
                t.decompose()
            title = soup.title.get_text() if soup.title else ""
            memo[url] = {"ok": r.status_code < 400, "text": clean(title + " " + soup.get_text(" ")),
                         "digits": re.sub(r"\D", "", html), "raw": html.lower()}
        except Exception as e:
            memo[url] = {"ok": False, "error": type(e).__name__}
    return memo[url]


async def main():
    db = json.loads((ROOT / "data" / "suppliers.json").read_text("utf-8"))
    memo, results = {}, []
    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient() as client:
        async def check(s):
            async with sem:
                items = [(k, v) for k, v in s["facts"].items()] + [(f"category:{c['id']}", c) for c in s["categories"]]
                out = []
                for key, f in items:
                    p = await page(client, f["url"], memo)
                    if not p["ok"]:
                        out.append({"key": key, "status": "страница недоступна"})
                        continue
                    if clean(f["evidence"]) not in p["text"]:
                        out.append({"key": key, "status": "цитаты нет"})
                        continue
                    # своя, независимая от конвейера сверка чисел: всё, что в значении, должно быть в цитате
                    nums = lambda t: set(re.findall(r"\d+", re.sub(r"(?<=\d)[ .](?=\d{3}\b)", "", t)))
                    if "value" in f and not nums(f["value"]) <= nums(f["evidence"]):
                        out.append({"key": key, "status": "числа не из цитаты"})
                        continue
                    if len(f["evidence"]) > 250:
                        out.append({"key": key, "status": "цитата длиннее 250"})
                        continue
                    out.append({"key": key, "status": "ok"})
                home = await page(client, s["site"], memo)
                pages_digits = ""
                for u in s["pages_checked"]:
                    pages_digits += (await page(client, u, memo)).get("digits", "")
                for ph in s["contacts"]["phones"]:
                    d = re.sub(r"\D", "", ph)[1:]
                    out.append({"key": "phone", "status": "ok" if d in pages_digits else "телефона нет"})
                pages_text = ""
                for u in s["pages_checked"]:
                    pages_text += (await page(client, u, memo)).get("raw", "")
                for em in s["contacts"]["emails"]:
                    out.append({"key": "email", "status": "ok" if em.lower() in pages_text else "почты нет"})
                results.append({"id": s["id"], "site_ok": home["ok"], "checks": out})
        await asyncio.gather(*[check(s) for s in db["suppliers"]])
    c = Counter(ch["status"] for r in results for ch in r["checks"])
    total = sum(c.values())
    summary = {"checked_at": datetime.now().isoformat(timespec="minutes"), "suppliers": len(results),
               "sites_reachable": sum(r["site_ok"] for r in results), "checks": total,
               "passed": c["ok"], "pass_rate": round(c["ok"] / total, 4) if total else None,
               "by_status": dict(c)}
    bad = [{"id": r["id"], "failed": [ch for ch in r["checks"] if ch["status"] != "ok"]}
           for r in results if any(ch["status"] != "ok" for ch in r["checks"])]
    (ROOT / "data" / "audit.json").write_text(json.dumps({"summary": summary, "failed": bad},
                                                         ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary["pass_rate"] and summary["pass_rate"] >= 0.95 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
