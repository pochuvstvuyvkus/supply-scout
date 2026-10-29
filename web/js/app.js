import {
  FACTS, PRIORITIES, rank, score, reasons, questions, rfqText, toCSV, bestInRow, completeness, catalogHit,
} from "./core.js?v=10";

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STATUSES = ["Новый", "Связались", "Запросили КП", "Получили прайс", "Работаем", "Не подходит"];
const NEED = [
  { key: "certificates", label: "Документы" },
  { key: "price_info", label: "Цены" },
  { key: "min_order", label: "Мин. заказ" },
  { key: "delivery", label: "Доставка" },
  { key: "horeca", label: "HoReCa" },
];
const SORTS = [{ id: "score", label: "Сначала подходящие" }, { id: "name", label: "По названию" }, { id: "complete", label: "Больше данных" }];
const PAGE_SIZES = [20, 50, 100];

const store = {
  get(k, d) { try { const v = localStorage.getItem("ss." + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ss." + k, JSON.stringify(v)); } catch { /* приватный режим */ } },
};

const S = {
  data: null,
  f: Object.assign({ q: "", category: "all", region: "ekb", need: [], priorities: [], sort: "score" }, store.get("filters", {})),
  page: 1, pageSize: 20,
  compare: store.get("compare", []),
  user: store.get("user", {}),
  api: false,
  view: "search",
};

const catName = (id) => S.data?.categories.find((c) => c.id === id)?.name || id;
const regName = (id) => ({ ekb: "Екатеринбург", msk: "Москва", russia: "По России" }[id] || id);
const byId = (id) => S.data.suppliers.find((s) => s.id === id);
const saveUser = () => { store.set("user", S.user); $("#listCount").textContent = Object.values(S.user).filter((u) => u.saved).length; };
const saveFilters = () => store.set("filters", S.f);

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.tm); toast.tm = setTimeout(() => { t.hidden = true; }, 2200);
}

/* ---------- загрузка ---------- */
async function load() {
  $("#cards").innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  $("#resCount").innerHTML = '<span class="muted">Загружаю…</span>';
  $("#progress").classList.add("on");
  const res = await fetch("data/suppliers.json", { cache: "no-cache" });
  S.data = await res.json();
  $("#progress").classList.remove("on");
  try {
    const h = await fetch("api/health", { cache: "no-store" });
    S.api = h.ok && (await h.json()).ok === true;
  } catch { S.api = false; }
  saveUser();
  renderAll();
  route();
}

/* ---------- фильтры ---------- */
function renderRegion() {
  const opts = [...S.data.regions, { id: "all", name: "Все" }];
  $("#regionSeg").innerHTML = opts.map((r) =>
    `<button data-region="${r.id}" class="${S.f.region === r.id ? "active" : ""}">${esc(r.name)}</button>`).join("");
}

function renderCats() {
  const base = { ...S.f, category: "all" };
  const all = rank(S.data.suppliers, base);
  const count = (id) => all.filter(({ s }) => s.categories.some((c) => c.id === id)).length;
  const items = [{ id: "all", name: "Все категории", n: all.length },
    ...S.data.categories.map((c) => ({ id: c.id, name: c.name, n: count(c.id) }))];
  $("#catList").innerHTML = items.map((c) =>
    `<button class="cat ${S.f.category === c.id ? "active" : ""}" data-cat="${c.id}"><span>${esc(c.name)}</span><span>${c.n}</span></button>`).join("");
}

function renderChips() {
  $("#needChips").innerHTML = NEED.map((n) =>
    `<button class="chip ${S.f.need.includes(n.key) ? "active" : ""}" data-need="${n.key}">${n.label}</button>`).join("");
  $("#prioChips").innerHTML = PRIORITIES.map((p) =>
    `<button class="chip ${S.f.priorities.includes(p.key) ? "active" : ""}" data-prio="${p.key}">${p.label}</button>`).join("");
  const n = S.f.need.length + S.f.priorities.length + (S.f.category !== "all" ? 1 : 0);
  $("#filterCount").hidden = !n; $("#filterCount").textContent = n;
}

function renderSort() {
  const cur = SORTS.find((s) => s.id === S.f.sort) || SORTS[0];
  $("#sortDd").innerHTML = `<button class="dd-btn" data-dd="sort">${cur.label}<svg class="ico" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg></button>`;
}

function openDropdown(anchor, items, current, onPick) {
  closeDropdown();
  const m = document.createElement("div");
  m.className = "dd-menu"; m.id = "ddMenu";
  m.innerHTML = items.map((i) => `<button class="dd-item ${i.id === current ? "active" : ""}" data-id="${i.id}">${esc(i.label)}</button>`).join("");
  anchor.parentElement.appendChild(m);
  m.addEventListener("click", (e) => { const b = e.target.closest(".dd-item"); if (b) { onPick(b.dataset.id); closeDropdown(); } });
  setTimeout(() => document.addEventListener("click", closeDropdown, { once: true }), 0);
}
function closeDropdown() { $("#ddMenu")?.remove(); }

/* ---------- результаты ---------- */
function ranked() {
  let r = rank(S.data.suppliers, S.f);
  if (S.f.sort === "name") r = r.sort((a, b) => a.s.name.localeCompare(b.s.name, "ru"));
  if (S.f.sort === "complete") r = r.sort((a, b) => completeness(b.s) - completeness(a.s) || b.sc.value - a.sc.value);
  return r;
}

function ring(v) {
  const c = 2 * Math.PI * 24;
  return `<div class="ring" aria-label="Соответствие ${v} из 100"><svg viewBox="0 0 56 56"><circle class="bg" cx="28" cy="28" r="24"/><circle class="fg" cx="28" cy="28" r="24" stroke-dasharray="${(c * v) / 100} ${c}"/></svg><b>${v}</b></div>`;
}

function factCell(s, key, label) {
  const v = s.facts?.[key]?.value;
  return `<div class="fact ${v ? "" : "none"}"><small>${label}</small><div>${v ? esc(v) : "нет данных"}</div></div>`;
}

function card({ s, sc }) {
  const u = S.user[s.id] || {};
  const inCmp = S.compare.includes(s.id);
  const phone = s.contacts.phones[0];
  const email = s.contacts.emails[0];
  const products = s.facts?.products?.value || s.requested_match?.evidence || "";
  const hit = catalogHit(s, S.f.q);
  return `<article class="card" data-id="${esc(s.id)}">
    ${ring(sc.value)}
    <div>
      <div class="card-top">
        <div style="min-width:0">
          <h2><button data-open="${esc(s.id)}">${esc(s.name)}</button></h2>
          <div class="sub">
            <span class="score-inline">${sc.value}/100</span>
            <a href="${esc(s.site)}" target="_blank" rel="noopener">${esc(s.host || s.domain)}</a>
            ${s.regions.map((r) => `<span class="tag reg">${regName(r)}</span>`).join("")}
            ${s.categories.slice(0, 3).map((c) => `<span class="tag">${esc(catName(c.id))}</span>`).join("")}
            ${s.categories.length > 3 ? `<span class="tag">+${s.categories.length - 3}</span>` : ""}
          </div>
        </div>
        ${u.saved ? `<span class="status-badge">${esc(u.status || "Новый")}</span>` : ""}
      </div>
      ${products ? `<p class="products">${esc(products)}</p>` : ""}
      ${hit ? `<p class="hit"><a href="${esc(s.site)}" target="_blank" rel="noopener">На сайте</a>«${esc(hit)}»</p>` : ""}
      <div class="facts">
        ${factCell(s, "min_order", "Мин. заказ")}${factCell(s, "price_info", "Цена")}
        ${factCell(s, "delivery", "Доставка")}${factCell(s, "certificates", "Документы")}
      </div>
      <div class="card-actions">
        ${phone ? `<a class="contact" href="tel:${phone.replace(/[^\d+]/g, "")}"><svg class="ico" viewBox="0 0 24 24"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2"/></svg>${esc(phone)}</a>` : ""}
        ${email ? `<a class="contact" href="mailto:${esc(email)}"><svg class="ico" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>${esc(email)}</a>` : ""}
        <span class="spacer"></span>
        <button class="btn ghost small toggle-btn ${inCmp ? "on" : ""}" data-cmp="${esc(s.id)}">${inCmp ? "В сравнении" : "Сравнить"}</button>
        <button class="btn ghost small toggle-btn ${u.saved ? "on" : ""}" data-save="${esc(s.id)}">${u.saved ? "В списке" : "В список"}</button>
        <button class="btn primary small" data-open="${esc(s.id)}">Подробнее</button>
      </div>
    </div>
  </article>`;
}

function renderResults() {
  const list = ranked();
  const pages = Math.max(1, Math.ceil(list.length / S.pageSize));
  S.page = Math.min(S.page, pages);
  const slice = list.slice((S.page - 1) * S.pageSize, S.page * S.pageSize);
  $("#resCount").textContent = `${list.length} ${plural(list.length, "поставщик", "поставщика", "поставщиков")}`;
  $("#cards").innerHTML = slice.length ? slice.map(card).join("") :
    `<div class="empty"><b>Ничего не нашлось</b></div>`;
  renderPager(list.length, pages);
  renderLive();
}

function renderPager(total, pages) {
  if (total <= PAGE_SIZES[0]) { $("#pager").innerHTML = ""; return; }
  const nums = [];
  for (let i = 1; i <= pages; i++) nums.push(`<button class="${i === S.page ? "active" : ""}" data-page="${i}">${i}</button>`);
  const sizes = PAGE_SIZES.map((n) => `<button class="${n === S.pageSize ? "active" : ""}" data-size="${n}">${n}</button>`).join("");
  $("#pager").innerHTML = `${nums.join("")}<span class="muted" style="margin:0 6px">по</span>${sizes}`;
}

const plural = (n, a, b, c) => { const m = n % 10, h = n % 100; return m === 1 && h !== 11 ? a : m >= 2 && m <= 4 && (h < 12 || h > 14) ? b : c; };

/* ---------- панель поставщика ---------- */
const ICON = {
  phone: '<svg class="ico" viewBox="0 0 24 24"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2"/></svg>',
  mail: '<svg class="ico" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>',
  site: '<svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/></svg>',
  doc: '<svg class="ico" viewBox="0 0 24 24"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/></svg>',
  cmp: '<svg class="ico" viewBox="0 0 24 24"><path d="M4 6h10M4 12h16M4 18h7"/></svg>',
  down: '<svg class="ico" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
};
const TILES = [
  { key: "min_order", label: "Мин. заказ" }, { key: "price_info", label: "Цена" },
  { key: "delivery", label: "Доставка" }, { key: "certificates", label: "Документы" },
  { key: "regions_served", label: "Регион работы" }, { key: "founded", label: "На рынке" },
];

function openDrawer(id, tab = "overview") {
  const s = byId(id); if (!s) return;
  const u = S.user[id] || {};
  const sc = score(s, S.f);
  const why = reasons(s, S.f);
  const qs = questions(s);
  const city = S.f.region === "msk" ? "Москву" : "Екатеринбург";
  const short = (url) => url.replace(/^https?:\/\//, "").replace(/\/$/, "");
  const phone = s.contacts.phones[0];
  const email = s.contacts.emails[0];
  const status = u.saved ? (u.status || "Новый") : null;

  const tiles = TILES.map((t) => {
    const f = s.facts?.[t.key];
    return `<div class="tile ${f ? "" : "none"}"><small>${t.label}</small><b>${f ? esc(f.value) : "нет на сайте"}</b>
      ${f ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">источник</a>` : ""}</div>`;
  }).join("");

  const srcRows = [{ key: "products", label: "Товары" }, { key: "city", label: "Город" }, { key: "address", label: "Адрес" },
    ...FACTS].filter((f) => s.facts?.[f.key]).map((f) => {
    const x = s.facts[f.key];
    return `<div class="src-row"><div class="k">${f.label}</div><div class="v">${esc(x.value)}</div>
      <blockquote>«${esc(x.evidence)}»</blockquote><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(short(x.url))}</a></div>`;
  }).join("") + s.categories.map((c) => `<div class="src-row"><div class="k">${esc(catName(c.id))}</div>
      <blockquote>«${esc(c.evidence)}»</blockquote><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(short(c.url))}</a></div>`).join("")
    + (s.inn ? `<div class="src-row"><div class="k">ИНН</div><div class="v">${esc(s.inn.value)}</div>
      <blockquote>«${esc(s.inn.evidence)}»</blockquote><a href="${esc(s.inn.url)}" target="_blank" rel="noopener">${esc(short(s.inn.url))}</a></div>` : "");

  const d = $("#drawer");
  d.innerHTML = `<div class="d-top">
    <div class="d-head">
      ${ring(sc.value)}
      <div class="d-title"><h2>${esc(s.name)}</h2>
        <div class="sub"><span>${esc(s.host || s.domain)}</span>
          ${s.regions.map((r) => `<span class="tag reg">${regName(r)}</span>`).join("")}
          ${s.categories.slice(0, 3).map((c) => `<span class="tag">${esc(catName(c.id))}</span>`).join("")}</div></div>
      <div class="dd d-status"><button class="dd-btn ${status ? "set" : ""}" data-dd="status">${status ? esc(status) : "В список"}${ICON.down}</button></div>
      <button class="icon-btn" data-close aria-label="Закрыть"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
    </div>
    <div class="d-bar">
      ${phone ? `<a class="btn primary small" href="tel:${phone.replace(/[^\d+]/g, "")}">${ICON.phone}${esc(phone)}</a>` : ""}
      ${email ? `<a class="btn ghost small" href="mailto:${esc(email)}">${ICON.mail}${esc(email)}</a>` : ""}
      <a class="btn ghost small" href="${esc(s.site)}" target="_blank" rel="noopener">${ICON.site}Сайт</a>
      <button class="btn ghost small" id="openRfq">${ICON.doc}Запрос КП</button>
      <button class="btn ghost small toggle-btn ${S.compare.includes(id) ? "on" : ""}" data-cmp="${esc(id)}">${ICON.cmp}${S.compare.includes(id) ? "В сравнении" : "Сравнить"}</button>
    </div>
    <div class="d-tabs" role="tablist">
      <button class="${tab === "overview" ? "active" : ""}" data-dtab="overview">Обзор</button>
      <button class="${tab === "sources" ? "active" : ""}" data-dtab="sources">Источники</button>
      <button class="${tab === "note" ? "active" : ""}" data-dtab="note">Заметка${u.note ? " ·" : ""}</button>
    </div></div>
    <div class="d-pane" data-pane="overview" ${tab === "overview" ? "" : "hidden"}>
      <div class="tiles">${tiles}</div>
      <div class="d-two">
        <div><h3>Плюсы и минусы</h3><ul class="why">${why.map((w) =>
          `<li><span class="mk ${w.ok === true ? "ok" : w.ok === null ? "mid" : "no"}">${w.ok === true ? "✓" : w.ok === null ? "~" : "✕"}</span>${esc(w.text)}</li>`).join("")}</ul></div>
        <div><h3>Уточнить при звонке</h3>${qs.length ? `<ol class="qs">${qs.map((q) => `<li>${esc(q)}</li>`).join("")}</ol>` : `<p class="muted">Всё есть на сайте</p>`}</div>
      </div>
      <div class="d-foot">
        ${[...s.contacts.phones.slice(1)].map((p) => `<a href="tel:${p.replace(/[^\d+]/g, "")}">${esc(p)}</a>`).join("")}
        ${s.inn ? `<span>ИНН ${esc(s.inn.value)}</span><a href="https://www.rusprofile.ru/search?query=${esc(s.inn.value)}" target="_blank" rel="noopener">Проверить контрагента</a>` : ""}
        <span class="muted">Проверено ${esc(s.checked_at)}</span>
      </div>
    </div>
    <div class="d-pane" data-pane="sources" ${tab === "sources" ? "" : "hidden"}><div class="src-list">${srcRows}</div></div>
    <div class="d-pane" data-pane="note" ${tab === "note" ? "" : "hidden"}><textarea class="note" id="note" rows="6">${esc(u.note || "")}</textarea></div>`;
  d.dataset.id = id;
  d.classList.add("open"); d.setAttribute("aria-hidden", "false");
  $("#backdrop").hidden = false;
  document.body.classList.add("locked");
  $("#openRfq").onclick = () => openRfq(s, city);
  $("#note").oninput = (e) => {
    S.user[id] = { ...(S.user[id] || {}), note: e.target.value, saved: true, status: (S.user[id] || {}).status || "Новый" };
    saveUser();
  };
}

function setDrawerTab(tab) {
  const d = $("#drawer");
  d.querySelectorAll("[data-dtab]").forEach((b) => b.classList.toggle("active", b.dataset.dtab === tab));
  d.querySelectorAll("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== tab; });
  if (tab === "note") $("#note").focus();
}

function openRfq(s, city) {
  const text = rfqText(s, { city, categoryNames: Object.fromEntries(S.data.categories.map((c) => [c.id, c.name])) });
  const email = s.contacts.emails[0];
  $("#modal").innerHTML = `<div class="modal-box rfq-box" role="dialog" aria-label="Запрос КП">
    <div class="modal-head"><h2>Запрос КП · ${esc(s.name)}</h2><button class="icon-btn" data-close-modal aria-label="Закрыть"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
    <div class="rfq-body"><textarea class="rfq" id="rfq">${esc(text)}</textarea>
      <div class="row"><button class="btn primary" id="copyRfq">Скопировать</button>
      ${email ? `<button class="btn ghost" id="mailRfq">Открыть в почте</button>` : ""}</div></div></div>`;
  $("#modal").hidden = false;
  $("#copyRfq").onclick = async () => {
    try { await navigator.clipboard.writeText($("#rfq").value); toast("Текст скопирован"); } catch { $("#rfq").select(); toast("Выделил текст, скопируйте"); }
  };
  if (email) $("#mailRfq").onclick = () => {
    location.href = `mailto:${email}?subject=${encodeURIComponent("Запрос коммерческого предложения")}&body=${encodeURIComponent($("#rfq").value)}`;
  };
}

function closeDrawer() {
  const d = $("#drawer");
  d.classList.remove("open"); d.setAttribute("aria-hidden", "true");
  document.body.classList.remove("locked");
  $("#backdrop").hidden = !$("#filters").classList.contains("open") ? true : false;
  renderTray();
  if (S.view === "compare") renderCompare();
  if (S.view === "list") renderBoard(); else renderResults();
}

/* ---------- сравнение ---------- */
function renderTray() {
  const n = S.compare.length;
  $("#cmpCount").textContent = n;
  $("#cmpCount").hidden = n === 0;
  if (S.view === "compare") renderCompare();
}

function renderCompare() {
  const list = S.compare.map(byId).filter(Boolean);
  const box = $("#cmpPage");
  if (!list.length) {
    box.innerHTML = `<div class="empty"><b>Пусто</b></div>`;
    return;
  }
  const rowsDef = [
    { key: "score", label: "Оценка" },
    { key: "regions", label: "Города" },
    { key: "cats", label: "Категории" },
    ...FACTS.map((f) => ({ key: f.key, label: f.label })),
    { key: "contacts", label: "Контакты" },
  ];
  const cell = (s, key, best) => {
    if (key === "score") return `<td><span class="score-pill">${score(s, S.f).value}</span></td>`;
    if (key === "regions") return `<td>${s.regions.map(regName).join(", ") || "—"}</td>`;
    if (key === "cats") return `<td>${s.categories.map((c) => esc(catName(c.id))).join("<br>")}</td>`;
    if (key === "contacts") return `<td>${s.contacts.phones.map((p) => `<a href="tel:${p.replace(/[^\d+]/g, "")}">${esc(p)}</a>`).join("<br>")}
      ${s.contacts.emails.map((e) => `<br><a href="mailto:${esc(e)}">${esc(e)}</a>`).join("")}</td>`;
    const v = s.facts?.[key]?.value;
    return v ? `<td class="${best ? "best" : ""}">${esc(v)}</td>` : `<td class="no">нет данных</td>`;
  };
  const body = rowsDef.map((r) => {
    const best = ["score", "regions", "contacts", "cats"].includes(r.key) || list.length < 2 ? list.map(() => false) : bestInRow(list, r.key);
    return `<tr><td>${r.label}</td>${list.map((s, i) => cell(s, r.key, best[i])).join("")}</tr>`;
  }).join("");
  box.innerHTML = `<div class="cmp-card"><div class="cmp-wrap"><table class="cmp"><thead><tr><th></th>${list.map((s) =>
    `<th><div class="cmp-h"><button class="cmp-name" data-open="${esc(s.id)}">${esc(s.name)}</button>
      <button class="icon-btn" data-uncmp="${esc(s.id)}" aria-label="Убрать"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
      <span class="cmp-host">${esc(s.host || s.domain)}</span></th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div></div>`;
}

/* ---------- мой список ---------- */
function renderBoard() {
  const saved = Object.entries(S.user).filter(([, u]) => u.saved).map(([id, u]) => ({ s: byId(id), u })).filter((x) => x.s);
  if (!saved.length) {
    $("#board").innerHTML = `<div class="empty" style="grid-column:1/-1"><b>Список пуст</b></div>`;
    return;
  }
  $("#board").innerHTML = STATUSES.map((st) => {
    const items = saved.filter(({ u }) => (u.status || "Новый") === st);
    return `<div class="col"><h3><span>${st}</span><span class="muted">${items.length}</span></h3>${items.map(({ s, u }) =>
      `<button class="mini" data-open="${esc(s.id)}"><b>${esc(s.name)}</b><small>${esc(s.contacts.phones[0] || s.contacts.emails[0] || s.host || s.domain)}</small>${u.note ? `<small>${esc(u.note.slice(0, 80))}</small>` : ""}</button>`).join("")}</div>`;
  }).join("");
}

function exportCsv() {
  const saved = Object.entries(S.user).filter(([, u]) => u.saved).map(([id]) => byId(id)).filter(Boolean);
  const rows = saved.length ? saved : ranked().map((x) => x.s);
  const csv = toCSV(rows, Object.fromEntries(S.data.categories.map((c) => [c.id, c.name])), S.user);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = `postavshchiki-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ---------- как это работает ---------- */
function renderHow() {
  const st = S.data.stats || {};
  const rej = Object.entries(st.facts_rejected || {}).slice(0, 8);
  const facts = S.data.suppliers.reduce((a, s) => a + Object.keys(s.facts || {}).length + s.categories.length, 0);
  $("#view-how").innerHTML = `
    <h1>Как это работает</h1>
    <p class="muted">Данные собраны ${esc(S.data.generated_at)} автоматически. Каждый факт в карточке подтверждён дословной цитатой с сайта поставщика и ссылкой на страницу.</p>
    <div class="flow">
      <div class="step"><div class="n">1</div><b>Поиск</b><p>Запросы по категориям и городам, отсев маркетплейсов, каталогов и справочников</p></div>
      <div class="step"><div class="n">2</div><b>Сайт</b><p>Главная и до 5 страниц: контакты, доставка, документы, условия для оптовиков</p></div>
      <div class="step"><div class="n">3</div><b>Модель</b><p>Gemini 2.5 Flash выписывает факты по строгой схеме и к каждому прикладывает цитату</p></div>
      <div class="step"><div class="n">4</div><b>Проверка без модели</b><p>Цитата дословно на странице, относится к полю, все числа и пункты значения взяты из неё</p></div>
      <div class="step"><div class="n">5</div><b>Решение</b><p>Оценка под ваши приоритеты, сравнение, вопросы для звонка, запрос КП, статусы</p></div>
    </div>
    <h2>Последний сбор</h2>
    <div class="stats">
      <div class="stat"><b>${st.candidates ?? "—"}</b><span>сайтов из поиска</span></div>
      <div class="stat"><b>${S.data.suppliers.length}</b><span>поставщиков прошли проверку</span></div>
      <div class="stat"><b>${facts}</b><span>фактов с цитатами</span></div>
      <div class="stat"><b>$${st.llm_cost_usd ?? "—"}</b><span>стоимость модели за сбор</span></div>
    </div>
    ${rej.length ? `<h2>Что отбросила проверка</h2><div class="rej">${rej.map(([k, v]) => `<div><span>${esc(k)}</span><b>${v}</b></div>`).join("")}</div>` : ""}
    <h2>Оценка соответствия</h2>
    <p>Город поставки, наличие документов, цен, условий доставки и минимального заказа, работа с HoReCa и полнота данных. Кнопки «Что важнее» усиливают нужные пункты. Оценка объясняется в карточке поставщика.</p>
    <h2>Код</h2>
    <p><a href="https://github.com/pochuvstvuyvkus/supply-scout" target="_blank" rel="noopener">github.com/pochuvstvuyvkus/supply-scout</a></p>`;
}

/* ---------- живой поиск (только с бэкендом) ---------- */
function renderLive() {
  const box = $("#live");
  if (!S.api) { box.hidden = true; return; }
  box.hidden = false;
  const q = S.f.q.trim();
  $("#liveHint").textContent = q ? `«${q}» · ${S.f.region === "msk" ? "Москва" : "Екатеринбург"}` : "";
  $("#liveBtn").disabled = !q || S.liveRunning;
}

function runLive() {
  const q = S.f.q.trim(); if (!q) return;
  S.liveRunning = true; renderLive();
  const log = $("#liveLog"); log.hidden = false; log.innerHTML = "";
  const city = S.f.region === "msk" ? "Москва" : "Екатеринбург";
  const es = new EventSource(`api/collect?q=${encodeURIComponent(q)}&city=${encodeURIComponent(city)}`);
  let added = 0;
  es.addEventListener("log", (e) => { log.insertAdjacentHTML("beforeend", `<li>${esc(e.data)}</li>`); log.scrollTop = log.scrollHeight; });
  es.addEventListener("card", (e) => {
    const c = JSON.parse(e.data);
    const i = S.data.suppliers.findIndex((s) => s.id === c.id);
    if (i >= 0) S.data.suppliers[i] = c; else S.data.suppliers.push(c);
    added++;
    log.insertAdjacentHTML("beforeend", `<li class="ok">${esc(c.name)}</li>`);
    renderCats(); renderResults();
  });
  const end = (msg) => { es.close(); S.liveRunning = false; renderLive(); toast(msg); };
  es.addEventListener("done", (e) => end(e.data === "busy" ? "Идёт другой поиск, попробуйте через минуту"
    : added ? `Добавлено: ${added}` : "Новых поставщиков не нашлось"));
  es.onerror = () => end("Поиск прерван");
}

/* ---------- маршруты и события ---------- */
function route() {
  const v = (location.hash || "#search").slice(1);
  S.view = ["search", "compare", "list", "how"].includes(v) ? v : "search";
  document.querySelectorAll(".view").forEach((el) => { el.hidden = el.id !== `view-${S.view}`; });
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === S.view));
  renderTray();
  if (S.view === "compare") renderCompare();
  if (S.view === "list") renderBoard();
  if (S.view === "how") renderHow();
  window.scrollTo(0, 0);
}

function renderAll() {
  $("#q").value = S.f.q; $("#qClear").hidden = !S.f.q;
  renderRegion(); renderCats(); renderChips(); renderSort(); renderResults(); renderTray();
}

function update() { S.page = 1; saveFilters(); renderCats(); renderChips(); renderRegion(); renderSort(); renderResults(); }

function toggleIn(arr, v) { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); else arr.push(v); }

function openSheet() { $("#filters").classList.add("open"); $("#backdrop").hidden = false; }
function closeSheet() { $("#filters").classList.remove("open"); if (!$("#drawer").classList.contains("open")) $("#backdrop").hidden = true; }

let qTimer;
$("#q").addEventListener("input", (e) => {
  $("#qClear").hidden = !e.target.value;
  clearTimeout(qTimer); qTimer = setTimeout(() => { S.f.q = e.target.value; update(); }, 150);
});
$("#qClear").onclick = () => { $("#q").value = ""; S.f.q = ""; $("#qClear").hidden = true; update(); $("#q").focus(); };
$("#openFilters").onclick = openSheet;
$("#resetFilters").onclick = () => { Object.assign(S.f, { q: "", category: "all", need: [], priorities: [], sort: "score" }); $("#q").value = ""; $("#qClear").hidden = true; update(); };
$("#exportCsv").onclick = exportCsv;
$("#cmpClear").onclick = () => { S.compare = []; store.set("compare", S.compare); renderTray(); renderResults(); };
$("#liveBtn").onclick = runLive;
$("#backdrop").onclick = () => { closeSheet(); if ($("#drawer").classList.contains("open")) closeDrawer(); };
window.addEventListener("hashchange", route);
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#modal").hidden) { $("#modal").hidden = true; return; }
  if ($("#drawer").classList.contains("open")) closeDrawer();
  closeSheet(); closeDropdown();
});

document.addEventListener("click", (e) => {
  const t = e.target.closest("button, a");
  if (!t) { if (e.target.id === "modal") $("#modal").hidden = true; return; }
  const d = t.dataset;
  if (d.view) { e.preventDefault(); location.hash = d.view; return; }
  if (d.region) { S.f.region = d.region; update(); return; }
  if (d.cat) { S.f.category = d.cat; update(); return; }
  if (d.need) { toggleIn(S.f.need, d.need); update(); return; }
  if (d.prio) { toggleIn(S.f.priorities, d.prio); update(); return; }
  if (d.dtab) { setDrawerTab(d.dtab); return; }
  if (d.dd === "status") {
    e.stopPropagation();
    const id = $("#drawer").dataset.id;
    const items = [...STATUSES.map((x) => ({ id: x, label: x })), ...(S.user[id]?.saved ? [{ id: "__remove", label: "Убрать из списка" }] : [])];
    openDropdown(t, items, S.user[id]?.saved ? (S.user[id].status || "Новый") : null, (val) => {
      const cur = S.user[id] || {};
      S.user[id] = val === "__remove" ? { ...cur, saved: false } : { ...cur, saved: true, status: val };
      saveUser();
      t.classList.toggle("set", S.user[id].saved);
      t.innerHTML = (S.user[id].saved ? esc(S.user[id].status) : "В список") + ICON.down;
    });
    return;
  }
  if (d.dd === "sort") { e.stopPropagation(); openDropdown(t, SORTS, S.f.sort, (id) => { S.f.sort = id; update(); }); return; }
  if (d.page) { S.page = +d.page; renderResults(); $("#cards").scrollIntoView({ block: "start" }); return; }
  if (d.size) { S.pageSize = +d.size; S.page = 1; renderResults(); return; }
  if (d.open) { openDrawer(d.open); return; }
  if (d.close !== undefined) { closeDrawer(); return; }
  if (d.closeSheet !== undefined) { closeSheet(); return; }
  if (d.closeModal !== undefined) { $("#modal").hidden = true; return; }
  if (d.cmp) {
    if (S.compare.includes(d.cmp)) S.compare = S.compare.filter((x) => x !== d.cmp);
    else if (S.compare.length >= 4) { toast("Сравнить можно до 4 поставщиков"); return; }
    else { S.compare.push(d.cmp); toast(`В сравнении: ${S.compare.length}`); }
    store.set("compare", S.compare);
    if (t.closest("#drawer")) { const on = S.compare.includes(d.cmp); t.classList.toggle("on", on); t.textContent = on ? "В сравнении" : "Сравнить"; }
    renderTray(); renderResults(); return;
  }
  if (d.uncmp) { S.compare = S.compare.filter((x) => x !== d.uncmp); store.set("compare", S.compare); renderTray(); if (S.view === "search") renderResults(); return; }
  if (d.save) {
    const u = S.user[d.save] || {};
    S.user[d.save] = { ...u, saved: !u.saved, status: u.status || "Новый" };
    saveUser(); renderResults(); toast(S.user[d.save].saved ? "Добавлен в список" : "Убран из списка"); return;
  }

});

load().catch((err) => {
  $("#progress").classList.remove("on");
  $("#cards").innerHTML = `<div class="empty"><b>Не удалось загрузить данные</b><span class="muted">${esc(err.message)}</span></div>`;
});
