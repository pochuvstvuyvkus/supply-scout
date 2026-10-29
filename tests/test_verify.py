"""Проверка, которая не даёт модели выдумывать: каждый случай, где ответ должен быть отброшен."""
from collector.fetch import extract_contacts, normalize_phone
from collector.search import is_blocked, parse_ddg
from collector.verify import check_fact, find_inn, inn_valid, verify

PAGES = [
    {"url": "https://example.ru/", "title": "ООО «Рыбный двор» — рыба оптом",
     "text": "Рыба и морепродукты оптом для ресторанов.\nМинимальный заказ от 5 000 рублей.\n"
             "Доставка по Екатеринбургу бесплатно от 10 000 ₽.\nЦены по запросу.",
     "contacts": {"phones": ["+7 343 222-33-44"], "emails": ["opt@example.ru"]}},
    {"url": "https://example.ru/docs", "title": "Документы",
     "text": "Вся продукция сопровождается ветеринарными документами в системе «Меркурий».",
     "contacts": {"phones": [], "emails": []}},
]


def fact(value, evidence, page=0):
    return {"value": value, "evidence": evidence, "page": page}


def test_quote_present_is_accepted_with_source_url():
    ok, reason = check_fact(fact("от 5000 рублей", "Минимальный заказ от 5 000 рублей"), PAGES, "min_order")
    assert reason is None and ok["url"] == "https://example.ru/"


def test_quote_not_on_site_is_rejected():
    ok, reason = check_fact(fact("от 3000 рублей", "Минимальный заказ от 3000 рублей"), PAGES, "min_order")
    assert ok is None and reason == "цитаты нет на сайте"


def test_number_not_in_quote_is_rejected():
    # цитата настоящая, но модель подменила число в значении
    ok, reason = check_fact(fact("от 7000 рублей", "Минимальный заказ от 5 000 рублей"), PAGES, "min_order")
    assert ok is None and "числа" in reason


def test_value_not_following_from_quote_is_rejected():
    ok, reason = check_fact(fact("сертификат ХАССП", "Рыба и морепродукты оптом для ресторанов."), PAGES, "certificates")
    assert ok is None and reason == "значение не следует из цитаты"


def test_wrong_page_number_is_fixed_by_search():
    ok, _ = check_fact(fact("ветеринарные документы в «Меркурий»",
                            "сопровождается ветеринарными документами в системе «Меркурий»", page=0),
                       PAGES, "certificates")
    assert ok["url"] == "https://example.ru/docs"


def test_normalization_quotes_yo_nbsp():
    ok, _ = check_fact(fact("документы в \"Меркурий\"",
                            'ветеринарными документами в системе "Меркурий"', page=1), PAGES, "certificates")
    assert ok is not None


def test_price_without_numbers_is_rejected():
    ok, reason = check_fact(fact("Цены по запросу", "Цены по запросу."), PAGES, "price_info")
    assert ok is None and reason == "цитата не о том поле"


def test_empty_value_is_silently_skipped():
    assert check_fact(fact(None, None, None), PAGES, "price_info") == (None, None)
    assert check_fact(fact("не указано", "x", 0), PAGES, "price_info") == (None, None)


def model_answer(**over):
    base = {k: {"value": None, "evidence": None, "page": None} for k in
            ["company_name", "products", "city", "address", "regions_served", "min_order",
             "price_info", "certificates", "delivery", "horeca", "founded"]}
    base.update({"site_kind": "supplier",
                 "sells_requested": {"value": True, "evidence": "Рыба и морепродукты оптом", "page": 0},
                 "categories": [{"id": "fish", "evidence": "Рыба и морепродукты оптом для ресторанов", "page": 0}],
                 "company_name": fact("Рыбный двор", "ООО «Рыбный двор»")})
    base.update(over)
    return base


SITE = {"domain": "example.ru", "home": "https://example.ru/", "title": "Рыбный двор", "pages": PAGES}


def test_supplier_card_built_from_verified_facts_only():
    card, rejected = verify(SITE, model_answer(
        min_order=fact("от 5000 рублей", "Минимальный заказ от 5 000 рублей"),
        price_info=fact("от 900 ₽/кг", "лосось от 900 ₽/кг")))  # цены на сайте нет
    assert card["name"] == "Рыбный двор"
    assert "min_order" in card["facts"] and "price_info" not in card["facts"]
    assert any(r["field"] == "price_info" for r in rejected)
    assert card["regions"] == ["ekb"]  # по коду телефона 343
    assert card["contacts"]["emails"] == ["opt@example.ru"]


def test_directory_is_not_a_supplier():
    card, rejected = verify(SITE, model_answer(site_kind="directory"))
    assert card is None and "не поставщик" in rejected[0]["reason"]


def test_category_with_fake_quote_is_dropped():
    card, _ = verify(SITE, model_answer(categories=[
        {"id": "fish", "evidence": "Рыба и морепродукты оптом для ресторанов", "page": 0},
        {"id": "meat", "evidence": "Мясо оптом", "page": 0}]))
    assert [c["id"] for c in card["categories"]] == ["fish"]


def test_no_confirmed_category_means_no_card():
    card, _ = verify(SITE, model_answer(categories=[{"id": "meat", "evidence": "Мясо оптом", "page": 0}]))
    assert card is None


def test_no_contacts_means_no_card():
    pages = [dict(p, contacts={"phones": [], "emails": []}) for p in PAGES]
    card, rejected = verify(dict(SITE, pages=pages), model_answer())
    assert card is None and rejected[-1]["field"] == "contacts"


def test_phone_normalization():
    assert normalize_phone("8 (343) 222-33-44") == "+7 343 222-33-44"
    assert normalize_phone("+7 912 000 11 22") == "+7 912 000-11-22"
    assert normalize_phone("12345") is None
    assert normalize_phone("+7 (123) 456-78-90") is None  # нет такого кода


def test_contacts_from_html():
    html = '<a href="tel:+73432223344">позвонить</a><a href="mailto:Sale@Ex.ru?subject=x">почта</a> logo@2x.png'
    c = extract_contacts(html, "звоните 8 800 555-35-35, logo@2x.png")
    assert c["phones"] == ["+7 343 222-33-44", "+7 800 555-35-35"]
    assert c["emails"] == ["sale@ex.ru"]


def test_blocked_domains_and_subdomains():
    assert is_blocked("avito.ru") and is_blocked("ekb.avito.ru") and not is_blocked("fish-opt.ru")


def test_parse_ddg_redirect_links():
    html = '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ffish.ru%2F&rut=1">Рыба</a>'
    assert parse_ddg(html) == [{"url": "https://fish.ru/", "title": "Рыба"}]


def test_inn_checksum():
    assert inn_valid("7707083893")        # Сбербанк
    assert not inn_valid("7707083894")
    assert inn_valid("500100732259")      # пример 12-значного ИНН ИП
    assert not inn_valid("500100732258")


def test_inn_found_only_with_valid_checksum():
    pages = [{"url": "https://x.ru/", "text": "ООО Ромашка ИНН 1234567890 КПП 1"},
             {"url": "https://x.ru/c", "text": "Реквизиты: ИНН/КПП 7707083893/773601001"}]
    assert find_inn(pages)["value"] == "7707083893"
    assert find_inn(pages)["url"] == "https://x.ru/c"


PAGES2 = [{"url": "https://y.ru/", "title": "Опт", "contacts": {"phones": ["+7 495 111-22-33"], "emails": []},
           "text": "Мороженое пломбир. Лапша быстрого приготовления. Скидка 3 700 руб на первый заказ. "
                   "Сборные перевозки от 3 700 руб. Ваш город Екатеринбург. Овощи оптом Екатеринбург. "
                   "Доставляем по Москве и области. Халяль. Быстрая доставка. Холодильники в аренду с доставкой 2 дня. "
                   "Сайт разработан студией Пиксель, ИНН 7707083893. Лосось охлажденный."}]


def test_discount_and_freight_are_not_prices():
    assert check_fact(fact("3 700 руб", "Скидка 3 700 руб на первый заказ"), PAGES2, "price_info")[1] == "цитата не о том поле"
    assert check_fact(fact("от 3 700 руб", "Сборные перевозки от 3 700 руб"), PAGES2, "price_info")[1] == "цитата не о том поле"


def test_slogans_and_rentals_are_not_delivery_terms():
    assert check_fact(fact("Быстрая доставка", "Быстрая доставка"), PAGES2, "delivery")[1] == "цитата не о том поле"
    assert check_fact(fact("в аренду с доставкой 2 дня", "Холодильники в аренду с доставкой 2 дня"), PAGES2, "delivery")[1] == "цитата не о том поле"


def test_city_switcher_widget_is_not_a_city():
    assert check_fact(fact("Екатеринбург", "Ваш город Екатеринбург"), PAGES2, "city")[1] == "цитата не о том поле"


def test_long_quote_is_rejected():
    long = "Лосось охлажденный. " * 20
    pages = [dict(PAGES2[0], text=long)]
    assert check_fact(fact("лосось", long.strip()), pages, "products")[1] == "слишком длинная цитата"


def test_every_list_item_must_be_in_quote():
    ok, reason = check_fact(fact("лосось, молочная продукция", "Лосось охлажденный"), PAGES2, "products")
    assert ok is None and reason == "значение не следует из цитаты"


def test_category_needs_its_keywords():
    answer = model_answer(categories=[
        {"id": "frozen", "evidence": "Мороженое пломбир", "page": 0},
        {"id": "frozen", "evidence": "Лапша быстрого приготовления", "page": 0},
        {"id": "asian", "evidence": "Халяль", "page": 0},
        {"id": "fish", "evidence": "Лосось охлажденный", "page": 0}])
    card, rejected = verify(dict(SITE, pages=PAGES2), answer)
    assert [c["id"] for c in card["categories"]] == ["fish"]
    assert sum(r["reason"] == "цитата не о категории" for r in rejected) >= 2


def test_web_studio_inn_is_ignored():
    assert find_inn(PAGES2) is None


def test_seo_city_list_does_not_make_region_but_delivery_does():
    card, _ = verify(dict(SITE, pages=PAGES2), model_answer(
        categories=[{"id": "fish", "evidence": "Лосось охлажденный", "page": 0}],
        regions_served=fact("Екатеринбург", "Овощи оптом Екатеринбург")))
    assert "ekb" not in card["regions"]
    card, _ = verify(dict(SITE, pages=PAGES2), model_answer(
        categories=[{"id": "fish", "evidence": "Лосось охлажденный", "page": 0}],
        regions_served=fact("по Москве и области", "Доставляем по Москве и области")))
    assert "msk" in card["regions"]
