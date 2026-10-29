"""Что ищем и где: категории, города, поисковые запросы, чёрный список доменов."""

CATEGORIES = [
    {"id": "rice", "name": "Рис и крупы",
     "queries": ["рис для суши оптом", "крупы оптом для ресторанов"]},
    {"id": "fish", "name": "Рыба и морепродукты",
     "queries": ["рыба и морепродукты оптом для ресторанов", "лосось охлажденный оптом"]},
    {"id": "meat", "name": "Мясо и птица",
     "queries": ["мясо оптом для ресторанов", "мясо птицы оптом поставщик"]},
    {"id": "veg", "name": "Овощи и фрукты",
     "queries": ["овощи и фрукты оптом для ресторанов", "поставка овощей для кафе оптом"]},
    {"id": "dairy", "name": "Молочная продукция и сыры",
     "queries": ["сыр оптом для ресторанов", "молочная продукция оптом для HoReCa"]},
    {"id": "asian", "name": "Продукты для паназиатской кухни",
     "queries": ["нори оптом", "продукты для суши оптом"]},
    {"id": "grocery", "name": "Бакалея, соусы и специи",
     "queries": ["бакалея оптом для ресторанов", "соусы оптом для ресторанов"]},
    {"id": "frozen", "name": "Замороженная продукция и полуфабрикаты",
     "queries": ["замороженные полуфабрикаты оптом для HoReCa", "замороженные продукты оптом для ресторанов"]},
    {"id": "packaging", "name": "Упаковка и одноразовая посуда",
     "queries": ["упаковка для доставки еды оптом", "одноразовая посуда оптом"]},
    {"id": "bakery", "name": "Хлеб и выпечка",
     "queries": ["хлеб оптом для ресторанов", "выпечка оптом для кафе"]},
]

CATEGORY_IDS = [c["id"] for c in CATEGORIES]
CATEGORY_NAMES = {c["id"]: c["name"] for c in CATEGORIES}

REGIONS = [
    {"id": "ekb", "name": "Екатеринбург", "aliases": ["екатеринбург", "свердловск", "урал"]},
    {"id": "msk", "name": "Москва", "aliases": ["москв", "подмосков"]},
]

# Каталоги, маркетплейсы, справочники и медиа: это не поставщики, а площадки.
BLOCKED_DOMAINS = {
    "avito.ru", "postavshikov.net", "agroserver.ru", "optomtovar.ru", "ozon.ru",
    "wildberries.ru", "market.yandex.ru", "yandex.ru", "ya.ru", "2gis.ru", "zoon.ru",
    "spravker.ru", "tiu.ru", "pulscen.ru", "satom.ru", "flagma.ru", "b2b-center.ru",
    "rusprofile.ru", "list-org.com", "vk.com", "youtube.com", "dzen.ru", "hh.ru",
    "wikipedia.org", "regmarkets.ru", "deal.by", "prom.ua", "alibaba.com",
    "made-in-china.com", "tenchat.ru", "yell.ru", "orgpage.ru", "fis.ru", "bizorg.su",
    "optlist.ru", "foodmarkets.ru", "prodtorg.ru", "unipack.ru", "allbiz.ru",
    "ru.all.biz", "tradedir.ru", "lavka.yandex.ru", "sbermarket.ru", "kuper.ru",
    "vprok.ru", "perekrestok.ru", "lenta.com", "magnit.ru", "auchan.ru", "otzovik.com",
    "irecommend.ru", "rbc.ru", "kommersant.ru", "vc.ru", "pikabu.ru", "t.me",
    "instagram.com", "facebook.com", "ok.ru", "rutube.ru", "dzen.ru", "mail.ru",
    "google.com", "duckduckgo.com", "bing.com", "kontur.ru", "checko.ru", "zakupki.gov.ru",
    "prodoptom.ru", "optovik.ru", "optrf.ru", "supl.biz", "metaprom.ru", "bizly.ru",
    "ru.kompass.com", "kompass.com", "ruspostavshik.ru", "torg.ru", "food-retail.ru",
    "foodnewsweek.ru", "restoclub.ru", "afisha.ru", "tripadvisor.ru", "chefmarket.ru",
}

SEARCH_RESULTS_PER_QUERY = 12
CANDIDATES_PER_CATEGORY_REGION = 9
PAGES_PER_SITE = 6
PAGE_TEXT_LIMIT = 7000
SITE_TEXT_LIMIT = 26000

LLM_MODELS = ["google/gemini-2.5-flash", "openai/gpt-4.1-mini"]
PROMPT_VERSION = "v3"
