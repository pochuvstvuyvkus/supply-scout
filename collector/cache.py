"""Дисковый кэш: повторный прогон не ходит в сеть и не платит за модель второй раз."""
import hashlib
import json
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


async def cached_json(kind: str, key: str, producer):
    h = hashlib.sha256(key.encode()).hexdigest()[:24]
    path = CACHE_DIR / kind / f"{h}.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    value = await producer()
    if value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), "utf-8")
    return value
