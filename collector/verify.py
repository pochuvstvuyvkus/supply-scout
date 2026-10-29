"""Детерминированная проверка ответа модели. Здесь нет LLM: только сверка с текстом сайта.

Факт попадает в карточку, только если:
  1) цитата (evidence) дословно есть на указанной странице (после нормализации пробелов, регистра, ё/е, кавычек);
  2) цитата короткая (до 250 символов) и показывается целиком;
  3) значение подкреплено цитатой: все числа значения есть в цитате, каждый пункт списка тоже, слов — не меньше 80%;
  4) цитата относится к полю: у цены рубли, у документов — сертификаты/декларации, у категории — её ключевые слова;
     стоп-слова отсекают скидки, тарифы перевозки, «цены по запросу», виджет выбора города, ИНН веб-студии.
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
MAX_QUOTE = 250

# Цитата должна относиться к полю: у каждого поля свои обязательные признаки и стоп-слова.
FIELD_RULES = {
    "price_info": {"need": r"\d[\d\s.,]*\s*(₽|руб|р\.|р\b|rub)|(₽|руб)\.?\s*\d",
                   "stop": r"скидк|перевоз|грузоперевоз|по запрос|доставк|бесплатн|%"},
    "min_order": {"need": r"минимальн|заказ|закупк|парти|отгрузк|мелк\w* опт",
                  "stop": r"зависит|по запрос|индивидуал|бесплатн|особые условия|скидк|уровн|цен[аы]|упаковк\w* по"},
    "delivery": {"need": r"\d|бесплатн|собственн|свой транспорт|своим транспорт|рефрижератор|ежедневн|график|"
                         r"день в день|следующий день|сутк|самовывоз|автопарк|автомобил",
                 "stop": r"аренд"},
    "certificates": {"need": r"сертифик|деклараци|ветеринар|вет\.|меркури|хассп|haccp|iso|гост|честный знак|"
                             r"документ|санитар|халяль|ветсвидетельств|сгр|ту\b",
                     "stop": r"документ,? подтверждающ|- документ|это документ|клиент|работающ\w* по принцип"},
    "horeca": {"need": r"ресторан|кафе|horeca|хорека|хорeca|общепит|общественн\w* питани|столов|гостиниц|отел|"
                       r"бар|фуд-?корт|кейтеринг|предприяти\w* питани|пиццери|суши-?бар",
               "stop": r"консалтинг|дистрибьютор|салон|если вы"},
    "founded": {"need": r"\d|лет|год", "stop": None},
    "city": {"need": None, "stop": r"ваш город|выбран|выберите город|выбрать город|на дом|купить|заказать"},
}

CATEGORY_KEYWORDS = {
    "rice": r"рис|круп|гречк|пшен|булгур|кускус|киноа|перлов|овсян",
    "fish": r"рыб|морепродукт|лосос|семг|форел|кревет|кальмар|мидии|мидий|краб|икр|тунец|тунц|осьминог|гребеш|"
            r"треск|минтай|судак|окун|угор|fish|сельд|скумбри|дорадо|сибас",
    "meat": r"мяс|говяд|свин|баран|птиц|кур|цыпл|индей|утк|телят|фарш|колбас|сосиск|ветчин|бекон|субпродукт|"
            r"стейк|котлет|халяль|бройлер",
    "veg": r"овощ|фрукт|зелен|ягод|картоф|томат|огур|салат|лук|морков|капуст|перец|перц|яблок|банан|цитрус|"
           r"грибы|гриб|авокадо|лимон",
    "dairy": r"молоч|молок|сыр(?!ь|ни|ок)|сливк|сливочн|масло сливоч|творог|сметан|йогурт|кефир|маскарпоне|"
             r"моцарел|пармезан|филадельфи|сгущ|dairy",
    "asian": r"нори|суши|ролл|васаби|имбир|соев|азиат|паназиат|японск|корейск|китайск|вьетнам|тайск|лапш|удон|"
             r"соба\b|рамен|тобико|масаго|кимчи|терияки|унаги|мирин|кунжут|рисов\w* бумаг|рисов\w* уксус|темпур|панко|"
             r"wok|вок",
    "grocery": r"бакале|соус|специ|припр|мук|масл|сахар|сол[ьи]|уксус|консерв|кетчуп|майонез|горчиц|круп|макарон|"
               r"паст[аы]|чай|кофе|сироп|приправ|мед\b|орех|снек",
    "frozen": r"заморож|замороз|полуфабрикат|шоков|глубок\w* замороз|морожен\w* (рыб|мяс|овощ|ягод)|пельмен|вареник|"
              r"frozen|охлажд\w* и заморож",
    "packaging": r"упаков|посуд|контейнер|ланч-?бокс|стакан|крышк|пакет|коробк|короб|лоток|лотк|салфет|пленк|"
                 r"фольг|одноразов|тар[аы]|бумаг|картон|приборы",
    "bakery": r"хлеб|выпеч|булк|булоч|батон|багет|лаваш|тесто|кондитер|пекар|круассан|бриошь|чиабат|бейгл|"
              r"тортиль|пирог|пирож|слойк|хлебобулоч",
}


CATEGORY_STOP = {
    "_all": r"перевоз|грузоперевоз|готов\w* блюд|от региональных поставщиков|доставка готов",
    "rice": r"рисом|рисов\w* бумаг|рисов\w* лапш|пирог|блюд",
    "meat": r"мясом|кулебяк|пирог|пельмен",
    "fish": r"рыбой|пирог|кулебяк|свежий улов",
    "grocery": r"сливочн",
    "packaging": r"бутылка дип|дип-пот|ведро",
}


def category_problem(cat: str, evidence: str) -> str | None:
    t = norm(evidence)
    if not re.search(CATEGORY_KEYWORDS[cat], t):
        return "цитата не о категории"
    for key in ("_all", cat):
        if key in CATEGORY_STOP and re.search(CATEGORY_STOP[key], t):
            return "цитата не о категории"
    if cat == "packaging" and len(evidence.split()) < 2:
        return "цитата не о категории"  # одно слово «Посуда» в меню продуктового сайта
    return None


def field_problem(field: str, value: str, evidence: str) -> str | None:
    rule = FIELD_RULES.get(field)
    if not rule:
        return None
    t = norm(value + " " + evidence)
    if rule["stop"] and re.search(rule["stop"], t):
        return "цитата не о том поле"
    if rule["need"] and not re.search(rule["need"], norm(value) if field == "price_info" else t):
        return "цитата не о том поле"
    return None


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
    if len(evidence) > MAX_QUOTE:
        return None, "слишком длинная цитата"
    url = find_quote(evidence, fact.get("page"), pages)
    if not url:
        return None, "цитаты нет на сайте"
    ev_nums = set(numbers(evidence))
    if any(n not in ev_nums for n in numbers(value)):
        return None, "в значении числа, которых нет в цитате"
    ev_stems = set(stem_words(evidence))
    # каждый пункт списка («лосось, форель, икра») должен быть в цитате; в целом — не меньше 80% слов
    for item in re.split(r"[,;]| и ", value):
        words = stem_words(item)
        if words and not any(w in ev_stems for w in words):
            return None, "значение не следует из цитаты"
    v_words = stem_words(value)
    if v_words and sum(1 for w in v_words if w in ev_stems) / len(v_words) < 0.8:
        return None, "значение не следует из цитаты"
    problem = field_problem(field, value, evidence)
    if problem:
        return None, problem
    if field == "price_info" and not re.search(r"[а-яa-z]{4,}", re.sub(r"руб\w*|цен\w*|за кг|за шт", "", norm(value))):
        return None, "цена без названия товара"
    if field == "certificates" and len(evidence.split()) < 2:
        return None, "цитата не о том поле"  # одиночное «Меркурий» — пункт меню, а не документы
    return {"value": value, "evidence": evidence, "url": url}, None


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


AGENCY_CONTEXT = re.compile(r"разработ|digital|сайт|агентств|студи|бренд упакован|продвижен|дизайн|хостинг", re.I)


def find_inn(pages: list[dict]) -> dict | None:
    found = []
    for p in pages:
        for m in INN_RE.finditer(p["text"]):
            if not inn_valid(m.group(1)):
                continue
            before = p["text"][max(0, m.start() - 80):m.start()]
            if AGENCY_CONTEXT.search(before):
                continue  # ИНН подрядчика в подвале сайта, а не поставщика
            rank = 0 if re.search(r"реквизит|контакт|о компании", p["url"] + " " + p.get("title", ""), re.I) else 1
            found.append((rank, {"value": m.group(1), "evidence": p["text"][max(0, m.start() - 40):m.end()].strip(),
                                 "url": p["url"]}))
    return sorted(found, key=lambda x: x[0])[0][1] if found else None


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


def catalog_lines(pages: list[dict], limit: int = 5000) -> str:
    """Короткие строки со страниц (пункты каталога, меню, списки товаров) для поиска по ассортименту."""
    seen, out, total = set(), [], 0
    for p in pages:
        for line in p["text"].split("\n"):
            t = re.sub(r"\s+", " ", line).strip()
            if 3 <= len(t) <= 80 and re.search(r"[а-яА-Я]{3}", t) and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
                total += len(t) + 3
                if total > limit:
                    return " · ".join(out)
    return " · ".join(out)


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
        ev = (c.get("evidence") or "").strip()
        if len(ev) > MAX_QUOTE:
            rejected.append({"field": f"category:{c['id']}", "reason": "слишком длинная цитата"})
            continue
        problem = category_problem(c["id"], ev)
        if problem:
            rejected.append({"field": f"category:{c['id']}", "reason": problem})
            continue
        url = find_quote(ev, c.get("page"), pages)
        if url:
            cats.append({"id": c["id"], "evidence": ev, "url": url})
        else:
            rejected.append({"field": f"category:{c['id']}", "reason": "цитаты нет на сайте"})

    if not cats:
        return None, rejected + [{"field": "categories", "reason": "нет подтверждённых категорий"}]

    contacts = {"phones": [], "emails": []}
    for p in pages:
        for k in contacts:
            for v in p.get("contacts", {}).get(k, []):
                if v not in contacts[k]:
                    contacts[k].append(v)
    contacts["phones"] = [ph for ph in contacts["phones"] if len(set(re.sub(r"\D", "", ph)[4:])) > 2]  # заглушки 999-99-99
    contacts = {k: v[:3] for k, v in contacts.items()}
    if not contacts["phones"] and not contacts["emails"]:
        return None, rejected + [{"field": "contacts", "reason": "на сайте нет ни телефона, ни почты"}]

    raw_name = facts.get("company_name", {}).get("value")
    name = clean_name(raw_name or site.get("title") or site["domain"], not raw_name, site["domain"])
    regions = set()
    for f in ("city", "address"):
        if f in facts:
            regions |= set(region_ids(facts[f]["evidence"]))
    if "regions_served" in facts:
        ev = facts["regions_served"]["evidence"]
        ids = set(region_ids(ev))
        if not re.search(r"достав|постав|работаем|привоз|отгруж|отправ|по всей|по росси", norm(ev)):
            ids.discard("ekb"); ids.discard("msk")  # «Овощи оптом Екатеринбург» в SEO-списке — не поставка
        regions |= ids
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
        "catalog": catalog_lines(pages),
    }, rejected
