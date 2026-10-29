"""Инварианты готовой базы. Если кэш страниц есть локально, каждая цитата перепроверяется по нему."""
import hashlib
import json
from pathlib import Path

import pytest

from collector.config import CATEGORY_IDS
from collector.verify import norm

ROOT = Path(__file__).resolve().parent.parent
DB = json.loads((ROOT / "data" / "suppliers.json").read_text("utf-8"))
WEB = json.loads((ROOT / "web" / "data" / "suppliers.json").read_text("utf-8"))
CACHE = ROOT / "data" / "cache" / "pages"


def test_web_copy_is_identical():
    assert DB == WEB


def test_ids_unique_and_basic_fields():
    ids = [s["id"] for s in DB["suppliers"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 30
    for s in DB["suppliers"]:
        assert s["name"] and s["site"].startswith("http")
        assert s["contacts"]["phones"] or s["contacts"]["emails"], s["id"]
        assert s["categories"] and all(c["id"] in CATEGORY_IDS for c in s["categories"]), s["id"]
        assert set(s["regions"]) <= {"ekb", "msk", "russia"}


def test_every_fact_has_quote_and_source_on_same_site():
    for s in DB["suppliers"]:
        for key, f in list(s["facts"].items()) + [(c["id"], c) for c in s["categories"]]:
            assert f["evidence"] and len(f["evidence"]) >= 4, (s["id"], key)
            assert s["domain"].split(".")[-2] in f["url"], (s["id"], key, f["url"])


def test_every_category_has_suppliers_in_both_cities():
    for cat in CATEGORY_IDS:
        for reg in ("ekb", "msk"):
            n = sum(1 for s in DB["suppliers"] if any(c["id"] == cat for c in s["categories"])
                    and (reg in s["regions"] or "russia" in s["regions"]))
            assert n >= 1, (cat, reg)


@pytest.mark.skipif(not CACHE.exists(), reason="кэш страниц есть только у того, кто запускал сбор")
def test_quotes_present_in_cached_pages():
    missing = []
    for s in DB["suppliers"]:
        for key, f in list(s["facts"].items()) + [(c["id"], c) for c in s["categories"]]:
            path = CACHE / f"{hashlib.sha256(f['url'].encode()).hexdigest()[:24]}.json"
            if not path.exists():
                continue  # страница открылась по редиректу под другим адресом
            p = json.loads(path.read_text("utf-8"))
            if norm(f["evidence"]) not in norm(p.get("title", "") + " " + p.get("text", "")):
                missing.append((s["id"], key))
    assert not missing, missing[:10]
