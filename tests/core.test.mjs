// node --test tests/
import test from "node:test";
import assert from "node:assert/strict";
import {
  filterSuppliers, score, rank, moqRub, questions, rfqText, toCSV, bestInRow, regionFit, textMatch, reasons,
} from "../web/js/core.js";

const f = (value) => ({ value, evidence: value, url: "https://x.ru/" });
const A = {
  id: "a.ru", name: "Альфа", domain: "a.ru", site: "https://a.ru/", regions: ["ekb"], checked_at: "2026-10-29",
  categories: [{ id: "fish", evidence: "Лосось охлаждённый оптом" }],
  contacts: { phones: ["+7 343 111-22-33"], emails: ["a@a.ru"] },
  facts: { products: f("лосось, форель"), min_order: f("от 5 000 ₽"), price_info: f("лосось от 990 ₽/кг"),
    certificates: f("ветеринарные документы"), delivery: f("бесплатно от 10 000 ₽") },
};
const B = {
  id: "b.ru", name: "Бета", domain: "b.ru", site: "https://b.ru/", regions: ["russia"], checked_at: "2026-10-29",
  categories: [{ id: "fish", evidence: "Морепродукты" }, { id: "asian", evidence: "Нори для роллов" }],
  contacts: { phones: [], emails: ["b@b.ru"] }, facts: { min_order: f("от 30 тыс. руб.") },
};
const C = {
  id: "c.ru", name: "Цэ", domain: "c.ru", site: "https://c.ru/", regions: ["msk"], checked_at: "2026-10-29",
  categories: [{ id: "meat", evidence: "Мясо" }], contacts: { phones: ["+7 495 000-00-00"], emails: [] }, facts: {},
};
const ALL = [A, B, C];

test("город: свой город — 1, поставки по России — 0.7, чужой город — 0", () => {
  assert.equal(regionFit(A, "ekb"), 1);
  assert.equal(regionFit(B, "ekb"), 0.7);
  assert.equal(regionFit(C, "ekb"), 0);
  assert.equal(regionFit(C, "all"), 1);
});

test("фильтр по категории, городу, тексту и обязательным фактам", () => {
  assert.deepEqual(filterSuppliers(ALL, { category: "fish", region: "ekb" }).map((s) => s.id), ["a.ru", "b.ru"]);
  assert.deepEqual(filterSuppliers(ALL, { region: "msk" }).map((s) => s.id), ["b.ru", "c.ru"]);
  assert.deepEqual(filterSuppliers(ALL, { region: "all", q: "нори" }).map((s) => s.id), ["b.ru"]);
  assert.deepEqual(filterSuppliers(ALL, { region: "all", need: ["certificates"] }).map((s) => s.id), ["a.ru"]);
});

test("поиск понимает окончания: «лососи» находит «лосось»", () => {
  assert.ok(textMatch(A, "лососи"));
  assert.ok(!textMatch(A, "говядина"));
});

test("оценка 0–100 и полный поставщик выше пустого", () => {
  const a = score(A, { region: "ekb" }).value;
  const b = score(B, { region: "ekb" }).value;
  assert.ok(a >= 0 && a <= 100 && b >= 0 && b <= 100);
  assert.ok(a > b);
  assert.deepEqual(rank(ALL, { region: "all" }).map((x) => x.s.id)[0], "a.ru");
});

test("приоритет меняет порядок: кому важен малый заказ", () => {
  const D = { ...B, id: "d.ru", name: "Дельта", facts: { min_order: f("от 3000 руб") } };
  const E = { ...B, id: "e.ru", name: "Эпсилон", facts: { certificates: f("сертификаты") } };
  assert.equal(rank([D, E], { region: "all", priorities: ["moq"] })[0].s.id, "d.ru");
  assert.equal(rank([D, E], { region: "all", priorities: ["docs"] })[0].s.id, "e.ru");
});

test("минимальный заказ в рублях разбирается, килограммы — нет", () => {
  assert.equal(moqRub(A), 5000);
  assert.equal(moqRub(B), 30000);
  assert.equal(moqRub({ facts: { min_order: f("от 20 кг") } }), null);
  assert.equal(moqRub(C), null);
});

test("вопросы для звонка — только про то, чего нет на сайте", () => {
  const qa = questions(A);
  assert.ok(!qa.some((q) => q.includes("минимальный")));
  assert.ok(qa.some((q) => q.includes("ресторанами")));
  assert.equal(questions(C).length, 6);
});

test("запрос КП содержит город, категории и недостающие вопросы", () => {
  const t = rfqText(B, { city: "Екатеринбург", categoryNames: { fish: "Рыба", asian: "Паназия" } });
  assert.match(t, /Екатеринбург/);
  assert.match(t, /рыба, паназия/);
  assert.match(t, /1\. /);
});

test("CSV: BOM, точка с запятой, экранирование кавычек", () => {
  const X = { ...A, name: 'ООО "Альфа"; опт' };
  const csv = toCSV([X], { fish: "Рыба" }, { "a.ru": { status: "Связались", note: "ок" } });
  assert.ok(csv.startsWith("﻿"));
  assert.match(csv, /"ООО ""Альфа""; опт"/);
  assert.match(csv, /Связались;ок/);
});

test("сравнение подсвечивает самый низкий минимальный заказ", () => {
  assert.deepEqual(bestInRow([A, B, C], "min_order"), [true, false, false]);
  assert.deepEqual(bestInRow([A, B, C], "certificates"), [true, false, false]);
});

test("объяснение оценки честно говорит, чего нет", () => {
  const r = reasons(C, { region: "ekb" });
  assert.ok(r.some((x) => x.ok === false && /Цен/.test(x.text)));
});

test("мин. заказ: берётся число у знака рубля, а не первое число", () => {
  const m = (v) => moqRub({ facts: { min_order: f(v) } });
  assert.equal(m("от 10 коробок или от 50.000 рублей"), 50000);
  assert.equal(m("Заявка от 5000р"), 5000);
  assert.equal(m("Минимальный первый заказ на 20 единиц продукции"), null);
  assert.equal(m("от 1 500 р."), 1500);
});

test("поиск по началу слова: «сыр» не находит сырники и сырьё", () => {
  const X = { ...C, facts: { products: f("сырники, сырьё для производства") } };
  const Y = { ...C, facts: { products: f("сыр моцарелла") } };
  assert.ok(!textMatch(X, "сыр"));
  assert.ok(textMatch(Y, "сыр"));
});

test("CSV: телефон и текст с сайта не превращаются в формулу Excel", () => {
  const X = { ...A, name: "=HYPERLINK(1)" };
  const csv = toCSV([X]);
  assert.match(csv, /'=HYPERLINK/);
  assert.match(csv, /8 343 111-22-33/);
});

test("оценка в карточке не зависит от фильтра города: чужой город — честное «не работает»", () => {
  assert.ok(score({ ...C, facts: { certificates: f("декларации") } }, { region: "ekb" }).value > 0);
  assert.ok(reasons(C, { region: "ekb" }).some((r) => r.ok === false && /не работает/.test(r.text)));
});
