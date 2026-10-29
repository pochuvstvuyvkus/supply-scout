"""API и раздача интерфейса.

    uvicorn api.main:app --port 8000

GET /api/health                  — жив ли сервер и есть ли ключ модели
GET /api/suppliers?category=&region=&q=  — собранная база с фильтрами
GET /api/collect?q=нори&city=Екатеринбург — живой поиск, поток событий (SSE): log, card, done
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from collector.extract import api_key
from collector.pipeline import OUT, WEB_OUT, run_query

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Supply Scout")
_lock = asyncio.Lock()  # один живой сбор за раз: защищает бюджет модели


def load_db() -> dict:
    return json.loads(OUT.read_text("utf-8"))


@app.get("/api/health")
def health():
    try:
        api_key()
        has_key = True
    except RuntimeError:
        has_key = False
    return {"ok": has_key, "suppliers": len(load_db()["suppliers"])}


@app.get("/api/suppliers")
def suppliers(category: str | None = None, region: str | None = None, q: str | None = None):
    db = load_db()
    res = db["suppliers"]
    if category:
        res = [s for s in res if any(c["id"] == category for c in s["categories"])]
    if region:
        res = [s for s in res if region in s["regions"] or "russia" in s["regions"]]
    if q:
        ql = q.lower()
        res = [s for s in res if ql in json.dumps(s, ensure_ascii=False).lower()]
    return JSONResponse({"count": len(res), "suppliers": res})


def sse(event: str, data) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@app.get("/api/collect")
async def collect(q: str = Query(..., min_length=2, max_length=80), city: str = "Екатеринбург"):
    async def stream():
        if _lock.locked():
            yield sse("log", "Другой поиск ещё идёт, подождите минуту")
            yield sse("done", "busy")
            return
        async with _lock:
            queue: asyncio.Queue = asyncio.Queue()
            task = asyncio.create_task(run_query(q, city, log=lambda m: queue.put_nowait(("log", m))))
            while not task.done() or not queue.empty():
                try:
                    kind, msg = await asyncio.wait_for(queue.get(), timeout=1)
                    yield sse(kind, msg)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
            cards = task.result() if not task.exception() else []
            if task.exception():
                yield sse("log", f"Ошибка: {type(task.exception()).__name__}")
            if cards:
                db = load_db()
                known = {s["id"]: i for i, s in enumerate(db["suppliers"])}
                for c in cards:
                    if c["id"] in known:
                        db["suppliers"][known[c["id"]]] = c
                    else:
                        db["suppliers"].append(c)
                    yield sse("card", c)
                for path in (OUT, WEB_OUT):
                    path.write_text(json.dumps(db, ensure_ascii=False, indent=1), "utf-8")
            yield sse("done", str(len(cards)))
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
