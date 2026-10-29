// Чистая логика без DOM: фильтрация, оценка, подсказки для решения. Покрыта тестами (tests/core.test.mjs).

export const FACTS = [
  { key: "min_order", label: "Минимальный заказ", ask: "Какой минимальный объём или сумма заказа?" },
  { key: "price_info", label: "Цена", ask: "Пришлите, пожалуйста, актуальный прайс-лист с оптовыми ценами." },
  { key: "certificates", label: "Документы", ask: "Какие документы есть на продукцию (декларации, сертификаты, ветеринарные документы в «Меркурии»)?" },
  { key: "delivery", label: "Доставка", ask: "Какие условия доставки: сроки, график, минимальная сумма для бесплатной доставки?" },
  { key: "regions_served", label: "Регион работы", ask: "Поставляете ли вы в наш город и как часто?" },
  { key: "horeca", label: "Работа с HoReCa", ask: "Работаете ли вы с ресторанами и сетями общепита, есть ли отсрочка платежа?" },
  { key: "founded", label: "На рынке", ask: null },
];

export const PRIORITIES = [
  { key: "docs", label: "Документы" },
  { key: "price", label: "Цена" },
  { key: "delivery", label: "Доставка" },
  { key: "moq", label: "Малый заказ" },
];

const BASE_WEIGHTS = { region: 3, docs: 2, price: 1.5, delivery: 1.5, moq: 1, horeca: 1, complete: 2 };

export const norm = (s) => (s || "").toLowerCase().replace(/ё/g, "е").replace(/\s+/g, " ").trim();

export function has(s, key) {
  return Boolean(s.facts && s.facts[key] && s.facts[key].value);
}

export function completeness(s) {
  const keys = FACTS.map((f) => f.key);
  return keys.filter((k) => has(s, k)).length / keys.length;
}

// Рубли из текста минимального заказа: число рядом со знаком рубля. «от 10 коробок или от 50.000 рублей» → 50000.
export function moqRub(s) {
  const v = (has(s, "min_order") ? s.facts.min_order.value : "").replace(/\u00a0/g, " ");
  const m = v.match(/(\d{1,3}(?:[ .]\d{3})+|\d+)(?:[.,]\d+)?\s*(тыс\.?\s*)?(?:₽|руб|р\.|р(?![а-яa-z])|rub)/i);
  if (!m) return null;
  let n = parseInt(m[1].replace(/[ .]/g, ""), 10);
  if (m[2]) n *= 1000;
  return Number.isFinite(n) ? n : null;
}

export function regionFit(s, region) {
  if (!region || region === "all") return 1;
  if ((s.regions || []).includes(region)) return 1;
  if ((s.regions || []).includes("russia")) return 0.7;
  return 0;
}

export function textMatch(s, q) {
  const query = norm(q);
  if (!query) return true;
  const hay = norm([
    s.name, s.domain,
    s.facts?.products?.value,
    ...(s.categories || []).map((c) => c.evidence),
    s.requested_match?.evidence,
  ].join(" "));
  // совпадение с начала слова: «сыр» находит «сыр, сыры», но не «сырьё» и «сырники»
  const words = hay.split(/[^a-zа-я0-9]+/);
  return query.split(" ").every((w) => {
    const stem = w.length > 4 ? w.slice(0, w.length - 1) : w;
    return words.some((x) => x.startsWith(stem) && (w.length > 4 || x.length <= w.length + 1));
  });
}

export function filterSuppliers(list, f) {
  return list.filter((s) =>
    (!f.category || f.category === "all" || (s.categories || []).some((c) => c.id === f.category)) &&
    regionFit(s, f.region) > 0 &&
    textMatch(s, f.q) &&
    (!f.need || f.need.every((k) => has(s, k))));
}

export function score(s, f = {}) {
  const pr = new Set(f.priorities || []);
  const w = { ...BASE_WEIGHTS };
  if (pr.has("docs")) w.docs *= 2.5;
  if (pr.has("price")) w.price *= 2.5;
  if (pr.has("delivery")) w.delivery *= 2.5;
  if (pr.has("moq")) w.moq *= 2.5;
  const parts = {
    region: regionFit(s, f.region),
    docs: has(s, "certificates") ? 1 : 0,
    price: has(s, "price_info") ? 1 : 0,
    delivery: has(s, "delivery") ? 1 : 0,
    moq: has(s, "min_order") ? (moqRub(s) !== null && moqRub(s) <= 10000 ? 1 : 0.7) : 0,
    horeca: has(s, "horeca") ? 1 : 0,
    complete: completeness(s),
  };
  const total = Object.keys(w).reduce((a, k) => a + w[k], 0);
  const got = Object.keys(w).reduce((a, k) => a + w[k] * parts[k], 0);
  return { value: Math.round((100 * got) / total), parts };
}

export function rank(list, f) {
  return filterSuppliers(list, f)
    .map((s) => ({ s, sc: score(s, f) }))
    .sort((a, b) => b.sc.value - a.sc.value || a.s.name.localeCompare(b.s.name, "ru"));
}

export function reasons(s, f = {}) {
  const out = [];
  const rf = regionFit(s, f.region);
  if (f.region && f.region !== "all") {
    out.push(rf === 1 ? { ok: true, text: "Работает в выбранном городе" }
      : rf > 0 ? { ok: null, text: "Поставляет по России" }
        : { ok: false, text: "В выбранном городе не работает" });
  }
  out.push(has(s, "certificates") ? { ok: true, text: "Указаны документы на продукцию" } : { ok: false, text: "Про документы на сайте нет" });
  out.push(has(s, "price_info") ? { ok: true, text: "Есть цены" } : { ok: false, text: "Цен на сайте нет" });
  out.push(has(s, "delivery") ? { ok: true, text: "Описаны условия доставки" } : { ok: false, text: "Условий доставки нет" });
  out.push(has(s, "min_order") ? { ok: true, text: `Минимальный заказ: ${s.facts.min_order.value}` } : { ok: false, text: "Минимальный заказ не указан" });
  if (has(s, "horeca")) out.push({ ok: true, text: "Работает с ресторанами и кафе" });
  return out;
}

export function questions(s) {
  return FACTS.filter((f) => f.ask && !has(s, f.key)).map((f) => f.ask);
}

export function rfqText(s, opts = {}) {
  const company = opts.company || "наша сеть ресторанов";
  const city = opts.city || "Екатеринбург";
  const cats = (s.categories || []).map((c) => opts.categoryNames?.[c.id] || c.id).join(", ");
  const qs = questions(s);
  const lines = [
    "Добрый день!",
    "",
    `Меня зовут ${opts.name || "[имя]"}, я отвечаю за закупки в компании ${company}. Ищем поставщика${cats ? ` (${cats.toLowerCase()})` : ""} с поставками в ${city}.`,
    "",
    "Просим прислать коммерческое предложение и прайс-лист.",
  ];
  if (qs.length) {
    lines.push("", "Также уточните, пожалуйста:");
    qs.forEach((q, i) => lines.push(`${i + 1}. ${q}`));
  }
  lines.push("", "Спасибо!", opts.contact || "[телефон, почта]");
  return lines.join("\n");
}

const csvCell = (v) => {
  let s = String(v ?? "");
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; // Excel не должен считать текст формулой
  return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function toCSV(rows, categoryNames = {}, state = {}) {
  const head = ["Поставщик", "ИНН", "Сайт", "Категории", "Города", "Телефоны", "Почта", "Мин. заказ", "Цена",
    "Документы", "Доставка", "Статус", "Заметка", "Проверено"];
  const body = rows.map((s) => [
    s.name, s.inn?.value || "", s.site,
    (s.categories || []).map((c) => categoryNames[c.id] || c.id).join(", "),
    (s.regions || []).join(", "),
    (s.contacts?.phones || []).map((p) => p.replace(/^\+7 /, "8 ")).join(", "),
    (s.contacts?.emails || []).join(", "),
    s.facts?.min_order?.value, s.facts?.price_info?.value, s.facts?.certificates?.value, s.facts?.delivery?.value,
    state[s.id]?.status || "", state[s.id]?.note || "", s.checked_at,
  ]);
  return "﻿" + [head, ...body].map((r) => r.map(csvCell).join(";")).join("\n");
}

// Лучшее значение в строке сравнения: подсветить у кого есть факт; для мин. заказа в рублях — у кого меньше.
export function bestInRow(list, key) {
  if (key === "min_order") {
    const vals = list.map((s) => moqRub(s));
    const nums = vals.filter((v) => v !== null);
    if (nums.length) {
      const min = Math.min(...nums);
      return list.map((s, i) => vals[i] === min);
    }
  }
  return list.map((s) => has(s, key));
}
