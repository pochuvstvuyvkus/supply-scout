"""Извлечение фактов о поставщике языковой моделью.

Модель обязана к каждому факту приложить дословную цитату со страницы и номер страницы.
Сама по себе модель ничего не решает: всё, что она вернула, потом проверяет verify.py.
"""
import json
import os
from pathlib import Path

import httpx

from .cache import cached_json
from .config import CATEGORIES, CATEGORY_IDS, LLM_MODELS, PROMPT_VERSION, SITE_TEXT_LIMIT

FACT_FIELDS = {
    "company_name": "название компании так, как оно написано на сайте",
    "products": "основные товары, которые компания продаёт (коротко, через запятую, словами с сайта)",
    "city": "город, где находится офис или склад компании",
    "address": "адрес офиса или склада",
    "regions_served": "куда компания поставляет (города, регионы, «по всей России»)",
    "min_order": "минимальный объём или сумма заказа",
    "price_info": "цены или условия цены (конкретные цифры, «цены по запросу» не считается)",
    "certificates": "сертификаты, декларации, ветеринарные документы, Меркурий, ХАССП и т.п.",
    "delivery": "условия доставки: сроки, бесплатная доставка от суммы, свой транспорт",
    "horeca": "работа с ресторанами, кафе, HoReCa, общепитом",
    "founded": "сколько лет на рынке или год основания",
}

SYSTEM = """Ты аналитик отдела закупок сети ресторанов. Тебе дают текст страниц сайта компании.
Задача: определить, поставщик ли это продуктов питания или упаковки для общепита, и выписать факты.

Строгие правила:
1. Каждый факт подтверждай ДОСЛОВНОЙ цитатой из текста (evidence) длиной 5–200 символов и номером страницы (page). Цитату копируй символ в символ, ничего не меняя.
2. Если факта на страницах нет, ставь value, evidence и page равными null. Ничего не додумывай и не бери из общих знаний.
3. value пиши коротко, теми же словами, что в цитате. Числа в value должны совпадать с числами в цитате.
4. site_kind: "supplier" — сама компания продаёт оптом или поставляет бизнесу; "directory" — каталог или агрегатор многих компаний; "retail_shop" — магазин для частных покупателей; "other" — всё остальное.
5. categories: только из списка, и для каждой категории нужна цитата, где видно, что компания продаёт такие товары.
"""


def schema() -> dict:
    fact = {"type": "object", "additionalProperties": False,
            "required": ["value", "evidence", "page"],
            "properties": {"value": {"type": ["string", "null"]},
                           "evidence": {"type": ["string", "null"]},
                           "page": {"type": ["integer", "null"]}}}
    props = {k: fact for k in FACT_FIELDS}
    props["site_kind"] = {"type": "string", "enum": ["supplier", "directory", "retail_shop", "other"]}
    props["sells_requested"] = {"type": "object", "additionalProperties": False,
                                "required": ["value", "evidence", "page"],
                                "properties": {"value": {"type": "boolean"},
                                               "evidence": {"type": ["string", "null"]},
                                               "page": {"type": ["integer", "null"]}}}
    props["categories"] = {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "evidence", "page"],
        "properties": {"id": {"type": "string", "enum": CATEGORY_IDS},
                       "evidence": {"type": "string"}, "page": {"type": "integer"}}}}
    return {"type": "object", "additionalProperties": False,
            "required": list(props), "properties": props}


def build_user_prompt(site: dict, requested: str) -> str:
    cats = "\n".join(f"- {c['id']}: {c['name']}" for c in CATEGORIES)
    fields = "\n".join(f"- {k}: {v}" for k, v in FACT_FIELDS.items())
    parts, total = [], 0
    for i, p in enumerate(site["pages"]):
        chunk = f"[PAGE {i}] {p['url']}\n{p['text']}\n"
        if total + len(chunk) > SITE_TEXT_LIMIT:
            chunk = chunk[: max(0, SITE_TEXT_LIMIT - total)]
        parts.append(chunk)
        total += len(chunk)
        if total >= SITE_TEXT_LIMIT:
            break
    return (f"Что ищет закупщик: {requested}\n"
            f"sells_requested: продаёт ли компания именно это (true/false с цитатой).\n\n"
            f"Категории:\n{cats}\n\nФакты:\n{fields}\n\nСТРАНИЦЫ САЙТА:\n" + "".join(parts))


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("OPENROUTER_API_KEY не задан (переменная окружения или .env)")


class LLMUnavailable(Exception):
    pass


async def call_llm(client: httpx.AsyncClient, user: str) -> tuple[dict, str, dict]:
    last_err = None
    for model in LLM_MODELS:  # цепочка запасных моделей
        for attempt in range(2):
            try:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key()}"},
                    json={"model": model, "messages": [{"role": "system", "content": SYSTEM},
                                                        {"role": "user", "content": user}],
                          "response_format": {"type": "json_schema", "json_schema": {
                              "name": "supplier", "strict": True, "schema": schema()}},
                          "usage": {"include": True}},
                    timeout=180)
                data = r.json()
                if r.status_code != 200 or "choices" not in data:
                    raise LLMUnavailable(f"{model}: HTTP {r.status_code} {str(data)[:200]}")
                content = data["choices"][0]["message"]["content"]
                return json.loads(content), model, data.get("usage", {})
            except (httpx.HTTPError, LLMUnavailable, json.JSONDecodeError, KeyError) as e:
                last_err = e
    raise LLMUnavailable(str(last_err))


async def extract(client: httpx.AsyncClient, site: dict, requested: str) -> dict:
    user = build_user_prompt(site, requested)
    key = f"{PROMPT_VERSION}|{LLM_MODELS[0]}|{user}"

    async def run():
        result, model, usage = await call_llm(client, user)
        return {"result": result, "model": model, "cost": usage.get("cost", 0)}
    return await cached_json("llm", key, run)
