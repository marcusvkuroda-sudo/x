/* Nossos Gastos — frontend */
(function () {
  const { fmt, fmtCompact, h, iso } = window.Charts;
  const { fold, placeKey, parseAmount, amountInput, activeInstallments } = window.Logic;

  const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

  const PRESETS = [
    ["this_month", "Este mês"],
    ["last_month", "Mês passado"],
    ["3m", "3 meses"],
    ["6m", "6 meses"],
    ["12m", "12 meses"],
    ["year", "Este ano"],
    ["all", "Tudo"],
  ];
  const TX_PAGE = 150;
  const VIEWS = ["dashboard", "transactions", "fixed", "import"];

  const state = {
    meta: { categories: [], sources: [] },
    txs: [],
    imports: [],
    view: "dashboard",
    preset: "this_month",
    month: null, // YYYY-MM when preset === "month"
    periodTouched: false,
    cat: null,
    source: "",
    files: [],
    review: {}, // import id -> { source, rows }
    lastUploadId: null,
    lastFiles: [],
    editing: null,
    formCat: "mercado",
    similar: null, // transactions from the same place as the one being edited
    txLimit: TX_PAGE,
    basis: "bill", // "bill": month of the statement · "purchase": purchase date
    bank: null, // Open Finance settings (never includes the secret)
    fixed: [],
    editingFixed: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const catMap = () => Object.fromEntries(state.meta.categories.map((c) => [c.key, c]));
  const catColor = (key) => `var(--cat-${key})`;

  /* ------------------------------------------------------------ utils */

  function parseDate(s) {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  const monthKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  const startOfMonth = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
  const endOfMonth = (d) => new Date(d.getFullYear(), d.getMonth() + 1, 0);
  const addMonths = (d, n) => {
    const r = new Date(d.getFullYear(), d.getMonth() + n, 1);
    r.setDate(Math.min(d.getDate(), endOfMonth(r).getDate()));
    return r;
  };
  const monthsSpanned = (a, b) => (b.getFullYear() - a.getFullYear()) * 12 + b.getMonth() - a.getMonth() + 1;
  const monthLabel = (key) => {
    const [y, m] = key.split("-").map(Number);
    return `${MONTHS[m - 1]} de ${y}`;
  };
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const today = () => {
    const t = new Date();
    t.setHours(0, 0, 0, 0);
    return t;
  };
  const sum = (arr) => arr.reduce((a, t) => a + t.amount_cents, 0);

  const store = {
    get(key) {
      try {
        return localStorage.getItem(key);
      } catch (_) {
        return null;
      }
    },
    set(key, value) {
      try {
        if (value == null) localStorage.removeItem(key);
        else localStorage.setItem(key, value);
      } catch (_) {}
    },
  };


  async function api(path, options = {}) {
    const res = await fetch(path, options);
    if (res.status === 204) return null;
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(body.message || validationText(body.detail) || `Erro ${res.status}`);
      err.body = body;
      err.status = res.status;
      throw err;
    }
    return body;
  }
  const jsonBody = (data, method = "POST") => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

  // FastAPI validation errors -> readable text; rowOf maps a position in the payload to a table row.
  function validationText(detail, rowOf = (i) => i + 1) {
    if (!Array.isArray(detail)) return "";
    return detail
      .map((d) => {
        const loc = d.loc || [];
        const i = loc.indexOf("transactions");
        const prefix = i >= 0 && Number.isInteger(loc[i + 1]) ? `Linha ${rowOf(loc[i + 1])}: ` : "";
        return prefix + String(d.msg || "").replace(/^Value error, /, "");
      })
      .join(" ");
  }

  let toastTimer;
  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
  }

  const safely =
    (fn) =>
    async (...args) => {
      try {
        await fn(...args);
      } catch (e) {
        toast(e.message || "Algo deu errado. Tente de novo.");
      }
    };

  /* ------------------------------------------------------------ loading */

  async function loadMeta() {
    state.meta = await api("/api/meta");
    $("#sources-list").replaceChildren(...state.meta.sources.map((s) => h("option", { value: s })));
    describeReader();
  }

  // Free local reading (PDF text, CSV, OFX) or paid Claude reading (also photos).
  function describeReader() {
    const claude = state.meta.reader === "claude";
    $("#upload-sub").textContent = claude
      ? "PDF da fatura, fotos das páginas ou CSV/OFX. O Claude lê e transforma tudo em lançamentos para vocês revisarem."
      : "Leitura gratuita: o app lê a fatura e transforma tudo em lançamentos para vocês revisarem.";
    $("#dropzone-hint").textContent = claude
      ? "PDF, CSV, OFX ou fotos (JPG, PNG, HEIC). Várias fotos da mesma fatura podem ir juntas."
      : "PDF da fatura baixado do app/site do banco, ou arquivo CSV/OFX exportado.";
  }

  async function loadTxs() {
    state.txs = await api("/api/transactions");
  }

  async function loadImports() {
    state.imports = await api("/api/imports");
    const pending = state.imports.filter((i) => i.status === "review").length;
    const badge = $("#import-badge");
    badge.hidden = pending === 0;
    badge.textContent = pending;
  }

  /* ------------------------------------------------------------ routing */

  function setView(view) {
    state.view = view;
    for (const v of VIEWS) $(`#view-${v}`).hidden = v !== view;
    document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-current", t.dataset.view === view ? "page" : "false"));
    if (location.hash !== `#${view}`) history.replaceState(null, "", `#${view}`);
    window.Charts.tooltip.hide();
    render();
    if (view === "import") loadBank(true);
    if (view === "fixed") safely(loadFixed)();
  }

  function render() {
    if (state.view === "dashboard") renderDashboard();
    else if (state.view === "transactions") renderTransactions();
    else if (state.view === "fixed") renderFixed();
    else renderImport();
  }

  /* ------------------------------------------------------------ period */

  // Card statements arrive after the month closes: while nothing was recorded this month,
  // open on the latest month with data instead of an empty screen.
  function autoPeriod() {
    const current = monthKey(today());
    const months = [...new Set(state.txs.map(monthOf))].filter((m) => m <= current).sort();
    if (!months.length || months.includes(current)) {
      state.preset = "this_month";
      state.month = null;
    } else {
      state.preset = "month";
      state.month = months[months.length - 1];
    }
  }

  function choosePeriod(preset, month = null) {
    state.preset = preset;
    state.month = month;
    state.periodTouched = true;
    renderDashboard();
  }

  function getPeriod() {
    const t = today();
    const p = state.preset;
    let start, end, prevStart, prevEnd, label, prevLabel;
    if (p === "this_month") {
      start = startOfMonth(t);
      end = endOfMonth(t);
      prevStart = addMonths(start, -1);
      prevEnd = addMonths(t, -1);
      label = `Gasto em ${MONTHS[t.getMonth()]}`;
      prevLabel = state.basis === "bill" ? MONTHS[prevStart.getMonth()] : "mesmo período do mês passado";
    } else if (p === "last_month") {
      start = addMonths(startOfMonth(t), -1);
      end = endOfMonth(start);
      prevStart = addMonths(start, -1);
      prevEnd = endOfMonth(prevStart);
      label = `Gasto em ${MONTHS[start.getMonth()]}`;
      prevLabel = MONTHS[prevStart.getMonth()];
    } else if (p === "month" && state.month) {
      start = parseDate(state.month + "-01");
      end = endOfMonth(start);
      prevStart = addMonths(start, -1);
      prevEnd = endOfMonth(prevStart);
      label = `Gasto em ${monthLabel(state.month)}`;
      prevLabel = MONTHS[prevStart.getMonth()];
    } else if (["3m", "6m", "12m"].includes(p)) {
      const n = parseInt(p);
      start = addMonths(startOfMonth(t), -(n - 1));
      end = endOfMonth(t);
      prevStart = addMonths(start, -n);
      prevEnd = endOfMonth(addMonths(start, -1));
      label = `Gasto nos últimos ${n} meses`;
      prevLabel = `${n} meses anteriores`;
    } else if (p === "year") {
      start = new Date(t.getFullYear(), 0, 1);
      end = new Date(t.getFullYear(), 11, 31);
      prevStart = new Date(t.getFullYear() - 1, 0, 1);
      prevEnd = new Date(t.getFullYear() - 1, t.getMonth(), t.getDate());
      label = `Gasto em ${t.getFullYear()}`;
      prevLabel = `mesmo período de ${t.getFullYear() - 1}`;
    } else {
      const dates = state.txs.map((x) => x.date).sort();
      start = dates.length ? startOfMonth(parseDate(dates[0])) : startOfMonth(t);
      const last = dates.length ? parseDate(dates[dates.length - 1]) : t;
      end = endOfMonth(last > t ? last : t);
      label = "Gasto total";
    }
    return { start, end, prevStart, prevEnd, label, prevLabel };
  }

  // Which month an entry counts in: by default the month of the statement it was charged on
  // (so a month's total matches the bank's statement); optionally the purchase date.
  const monthOf = (t) => (state.basis === "bill" ? t.bill_month || t.date.slice(0, 7) : t.date.slice(0, 7));

  const inRange = (tx, a, b) => {
    if (state.basis === "bill") {
      const m = monthOf(tx);
      return m >= monthKey(a) && m <= monthKey(b);
    }
    const d = tx.date;
    return d >= iso(a) && d <= iso(b);
  };

  /* ------------------------------------------------------------ dashboard */

  function renderFilters() {
    $("#period-seg").replaceChildren(
      ...PRESETS.map(([key, label]) =>
        h("button", { type: "button", "aria-pressed": String(state.preset === key), text: label, onclick: () => choosePeriod(key) })
      )
    );

    $("#basis-seg").replaceChildren(
      ...[
        ["bill", "🧾 Mês da fatura"],
        ["purchase", "🛒 Data da compra"],
      ].map(([key, label]) =>
        h("button", {
          type: "button",
          "aria-pressed": String(state.basis === key),
          text: label,
          title: key === "bill" ? "Cada compra conta no mês da fatura em que foi cobrada: o total do mês bate com a fatura" : "Cada compra conta no mês em que foi feita",
          onclick: () => {
            state.basis = key;
            store.set("basis", key);
            renderDashboard();
          },
        })
      )
    );

    const months = [...new Set(state.txs.map(monthOf))].sort().reverse();
    const ms = $("#month-select");
    ms.replaceChildren(h("option", { value: "", text: "📅 Escolher mês…" }), ...months.map((m) => h("option", { value: m, text: cap(monthLabel(m)) })));
    ms.value = state.preset === "month" ? state.month : "";

    const sources = [...new Set(state.txs.map((t) => t.source).filter(Boolean))].sort();
    const ss = $("#source-select");
    ss.hidden = sources.length < 2;
    ss.replaceChildren(h("option", { value: "", text: "💳 Todos os cartões" }), ...sources.map((s) => h("option", { value: s, text: s })));
    ss.value = state.source;

    $("#cat-chips").replaceChildren(
      h("button", { class: "chip", type: "button", "aria-pressed": String(!state.cat), onclick: () => setCat(null) }, "✨ Todas"),
      ...state.meta.categories.map((c) =>
        h(
          "button",
          { class: "chip", type: "button", "aria-pressed": String(state.cat === c.key), onclick: () => setCat(state.cat === c.key ? null : c.key) },
          h("span", { class: "dot", style: `background:${catColor(c.key)}` }),
          `${c.icon} ${c.label}`
        )
      )
    );
  }

  function setCat(key) {
    state.cat = key;
    renderDashboard();
  }

  function deltaText(current, previous) {
    if (!previous) return current > 0 ? { text: "novo", cls: "up" } : null;
    const pct = Math.round(((current - previous) / Math.abs(previous)) * 100);
    if (pct === 0) return { text: "= igual", cls: "" };
    return { text: `${pct > 0 ? "▲" : "▼"} ${Math.abs(pct)}%`, cls: pct > 0 ? "up" : "down" };
  }

  function renderDashboard() {
    if (!state.periodTouched) autoPeriod();
    renderFilters();
    const empty = state.txs.length === 0;
    $("#dash-empty").hidden = !empty;
    $("#dash").hidden = empty;
    if (empty) return;

    const cats = state.meta.categories;
    const cmap = catMap();
    const period = getPeriod();
    const base = state.txs.filter((t) => !state.source || t.source === state.source);
    const scoped = base.filter((t) => !state.cat || t.category === state.cat);
    const inPeriod = scoped.filter((t) => inRange(t, period.start, period.end));
    const t0 = today();

    // ---- KPIs
    const total = sum(inPeriod);
    $("#kpi-total-label").textContent = period.label + (state.cat ? ` · ${cmap[state.cat].label}` : "");
    $("#kpi-total").textContent = fmt(total);
    const deltaEl = $("#kpi-total-delta");
    deltaEl.replaceChildren();
    if (period.prevStart) {
      const prev = sum(scoped.filter((t) => inRange(t, period.prevStart, period.prevEnd)));
      if (prev > 0) {
        const pct = ((total - prev) / prev) * 100;
        const up = total > prev;
        deltaEl.append(h("span", { class: `delta ${up ? "up" : "down"}` }, `${up ? "▲" : "▼"} ${Math.abs(pct).toFixed(0)}%`), ` vs ${period.prevLabel} (${fmt(prev)})`);
      } else {
        deltaEl.textContent = `Sem gastos em ${period.prevLabel} para comparar`;
      }
    } else {
      deltaEl.textContent = `${plural(inPeriod.length, "lançamento", "lançamentos")} desde ${MONTHS[period.start.getMonth()]} de ${period.start.getFullYear()}`;
    }

    // Monthly series: 12 months ending at the period's last month (or the whole period if longer, max 24).
    const endMonth = startOfMonth(period.end > t0 && state.preset === "all" ? t0 : period.end);
    const nMonths = Math.min(24, Math.max(12, monthsSpanned(period.start, period.end)));
    const monthKeys = [];
    for (let i = nMonths - 1; i >= 0; i--) monthKeys.push(monthKey(addMonths(endMonth, -i)));
    const byMonth = Object.fromEntries(monthKeys.map((k) => [k, {}]));
    for (const t of scoped) {
      const k = monthOf(t);
      if (byMonth[k]) byMonth[k][t.category] = (byMonth[k][t.category] || 0) + t.amount_cents;
    }
    const startKey = monthKey(period.start);
    const endKey = monthKey(period.end);
    const months = monthKeys.map((k, i) => {
      const [y, m] = k.split("-").map(Number);
      const values = byMonth[k];
      return {
        key: k,
        label: cap(monthLabel(k)),
        short: MONTHS_SHORT[m - 1],
        year: String(y),
        showYear: i === 0 || m === 1,
        values,
        total: Object.values(values).reduce((a, b) => a + b, 0),
        active: k >= startKey && k <= endKey,
      };
    });

    window.Charts.sparkline($("#kpi-spark"), months.slice(-12).map((m) => m.total), "var(--accent)");

    // Average. A month still in progress would drag the monthly average down, so it is left out.
    // By statement month, a month counts whole (its statement is already closed when imported).
    const bill = state.basis === "bill";
    // By statement month, purchases spread over the statement's own dates (part of them in the
    // month before): the calendar and the daily average use those dates.
    const purchaseSpan = (() => {
      if (!bill || !inPeriod.length) return { start: period.start, end: period.end };
      const dates = inPeriod.map((t) => t.date).sort();
      return { start: parseDate(dates[0]), end: parseDate(dates[dates.length - 1]) };
    })();
    const lastDay = bill ? endOfMonth(t0) : t0;
    const elapsedEnd = period.end > lastDay ? lastDay : period.end;
    const days = Math.max(1, Math.round((elapsedEnd - period.start) / 864e5) + 1);
    const elapsedMonths = monthsSpanned(period.start, elapsedEnd);
    if (elapsedMonths > 1) {
      const currentKey = monthKey(t0);
      const partial = !bill && monthKey(elapsedEnd) === currentKey && t0.getDate() < endOfMonth(t0).getDate();
      const fullTotal = partial ? total - sum(inPeriod.filter((t) => monthOf(t) === currentKey)) : total;
      $("#kpi-avg-label").textContent = "Média por mês";
      $("#kpi-avg").textContent = fmt(Math.round(fullTotal / (partial ? elapsedMonths - 1 : elapsedMonths)));
      $("#kpi-avg-sub").textContent = partial ? `sem contar ${MONTHS[t0.getMonth()]}, ainda em andamento` : `≈ ${fmt(Math.round(total / days))} por dia`;
    } else {
      const spanDays = bill ? Math.round((purchaseSpan.end - purchaseSpan.start) / 864e5) + 1 : days;
      $("#kpi-avg-label").textContent = "Média por dia";
      $("#kpi-avg").textContent = fmt(Math.round(total / spanDays));
      $("#kpi-avg-sub").textContent = bill
        ? `${plural(spanDays, "dia", "dias")} de compras (${purchaseSpan.start.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })} a ${purchaseSpan.end.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })})`
        : `em ${plural(days, "dia", "dias")}`;
    }

    // Categories (ignore the category filter so the whole picture stays visible)
    const periodAll = base.filter((t) => inRange(t, period.start, period.end));
    const byCat = {};
    const countCat = {};
    for (const t of periodAll) {
      byCat[t.category] = (byCat[t.category] || 0) + t.amount_cents;
      countCat[t.category] = (countCat[t.category] || 0) + 1;
    }
    const byCatPrev = {};
    if (period.prevStart) {
      for (const t of base) if (inRange(t, period.prevStart, period.prevEnd)) byCatPrev[t.category] = (byCatPrev[t.category] || 0) + t.amount_cents;
    }
    // Without any spending in the previous period every category would read "novo": skip it.
    const compare = Object.keys(byCatPrev).length > 0;
    const catTotal = Object.values(byCat).reduce((a, b) => a + Math.max(0, b), 0);
    const ranked = cats.filter((c) => byCat[c.key]).sort((a, b) => byCat[b.key] - byCat[a.key]);

    const top = ranked[0];
    const topEl = $("#kpi-topcat");
    topEl.replaceChildren();
    if (top) {
      topEl.append(h("div", { class: "cat-bubble", style: `--c:${catColor(top.key)}`, text: top.icon }), h("div", { class: "kpi-value", style: "font-size:20px", text: top.label }));
      $("#kpi-topcat-sub").textContent = `${fmt(byCat[top.key])} · ${catTotal ? Math.round((byCat[top.key] / catTotal) * 100) : 0}% do total`;
    } else {
      topEl.append(h("div", { class: "kpi-value", text: "–" }));
      $("#kpi-topcat-sub").textContent = "Sem gastos no período";
    }

    $("#kpi-count").textContent = inPeriod.length.toLocaleString("pt-BR");
    const expenses = inPeriod.filter((t) => t.amount_cents > 0);
    $("#kpi-count-sub").textContent = expenses.length ? `ticket médio ${fmt(Math.round(sum(expenses) / expenses.length))}` : "";

    // ---- Composition + category bars
    const compo = $("#compo");
    compo.replaceChildren(
      ...cats
        .filter((c) => byCat[c.key] > 0)
        .map((c) => {
          const seg = h("div", { style: `flex:${byCat[c.key]};background:${catColor(c.key)}`, tabindex: 0 });
          window.Charts.bindTooltip(seg, () => ({
            title: `${c.icon} ${c.label}`,
            rows: [
              { label: "No período", value: fmt(byCat[c.key]) },
              { label: "Participação", value: `${((byCat[c.key] / catTotal) * 100).toFixed(1)}%` },
            ],
          }));
          seg.addEventListener("click", () => setCat(state.cat === c.key ? null : c.key));
          return seg;
        })
    );
    compo.hidden = catTotal === 0;
    window.Charts.hbars(
      $("#chart-categories"),
      ranked.map((c) => {
        const delta = compare ? deltaText(byCat[c.key], byCatPrev[c.key] || 0) : null;
        return {
          key: c.key,
          label: c.label,
          icon: c.icon,
          color: catColor(c.key),
          value: byCat[c.key],
          pct: catTotal ? `${Math.round((byCat[c.key] / catTotal) * 100)}%` : "",
          sub: delta ? delta.text : plural(countCat[c.key], "lanç.", "lanç."),
          subClass: delta ? delta.cls : null,
          dim: state.cat && state.cat !== c.key,
          tooltip: () => ({
            title: `${c.icon} ${c.label}`,
            rows: [
              { label: "No período", value: fmt(byCat[c.key]) },
              { label: "Lançamentos", value: String(countCat[c.key]) },
              ...(compare ? [{ label: `Em ${period.prevLabel}`, value: fmt(byCatPrev[c.key] || 0) }] : []),
            ],
          }),
        };
      }),
      { onClick: (k) => setCat(state.cat === k ? null : k) }
    );
    if (!ranked.length) $("#chart-categories").replaceChildren(h("p", { class: "muted", text: "Nenhum gasto neste período." }));
    $("#cat-sub").textContent = compare ? `Variação vs ${period.prevLabel} · toque para filtrar` : "Toque numa categoria para filtrar";

    // ---- Monthly chart (after the category card, whose height it matches)
    const shownCats = cats.filter((c) => !state.cat || c.key === state.cat).map((c) => ({ ...c, color: catColor(c.key) }));
    $("#monthly-sub").textContent = state.cat ? `${cmap[state.cat].label}, mês a mês` : `Gastos por categoria, ${nMonths} meses ${bill ? "(pelo mês da fatura)" : "(pela data da compra)"} · toque num mês para ver só ele`;
    window.Charts.stackedColumns($("#chart-monthly"), { months, cats: shownCats, onClick: (k) => choosePeriod("month", k) });
    $("#legend-monthly").replaceChildren(
      ...shownCats.filter((c) => months.some((m) => m.values[c.key])).map((c) => h("span", {}, h("i", { style: `background:${c.color}` }), c.label))
    );

    // ---- Heatmap
    const daily = new Map();
    const counts = new Map();
    for (const t of inPeriod) {
      daily.set(t.date, (daily.get(t.date) || 0) + t.amount_cents);
      counts.set(t.date, (counts.get(t.date) || 0) + 1);
    }
    const { start: heatStart, end: heatEnd } = purchaseSpan;
    const heat = window.Charts.calendarHeatmap($("#chart-heat"), $("#heat-legend"), { start: heatStart, end: heatEnd, daily, counts });
    $("#heat-sub").textContent = heat.truncated ? "Últimos 12 meses do período · quanto mais escuro, mais gastamos" : "Quanto mais escuro, mais gastamos no dia";

    // ---- Weekday averages
    const wdTotals = [0, 0, 0, 0, 0, 0, 0];
    const wdDays = [0, 0, 0, 0, 0, 0, 0];
    const wdActive = [0, 0, 0, 0, 0, 0, 0];
    for (let d = new Date(heatStart); d <= (heatEnd > t0 ? t0 : heatEnd); d.setDate(d.getDate() + 1)) wdDays[d.getDay()]++;
    for (const [k, v] of daily) {
      const wd = parseDate(k).getDay();
      wdTotals[wd] += v;
      if (v > 0) wdActive[wd]++;
    }
    window.Charts.weekBars($("#chart-week"), wdTotals.map((v, i) => (wdDays[i] ? Math.round(v / wdDays[i]) : 0)), wdActive);

    // ---- Merchants
    const merchants = {};
    for (const t of inPeriod) {
      const name = t.merchant || t.description;
      const m = (merchants[name.toLowerCase()] ||= { name, total: 0, count: 0, cats: {} });
      m.total += t.amount_cents;
      m.count++;
      m.cats[t.category] = (m.cats[t.category] || 0) + t.amount_cents;
    }
    const topMerchants = Object.values(merchants)
      .filter((m) => m.total > 0)
      .sort((a, b) => b.total - a.total)
      .slice(0, 10);
    window.Charts.hbars(
      $("#chart-merchants"),
      topMerchants.map((m) => {
        const catKey = Object.entries(m.cats).sort((a, b) => b[1] - a[1])[0][0];
        const c = cmap[catKey] || cmap.outros;
        return {
          key: m.name,
          label: m.name,
          icon: c.icon,
          color: catColor(c.key),
          value: m.total,
          sub: plural(m.count, "compra", "compras"),
          tooltip: () => ({
            title: m.name,
            rows: [
              { color: catColor(c.key), label: `${c.icon} ${c.label}`, value: fmt(m.total) },
              { label: "Compras", value: String(m.count) },
              { label: "Média por compra", value: fmt(Math.round(m.total / m.count)) },
            ],
          }),
        };
      }),
      { compact: true }
    );
    if (!topMerchants.length) $("#chart-merchants").replaceChildren(h("p", { class: "muted", text: "Nenhum gasto neste período." }));

    // ---- Installments (independent of the period: what is still to come)
    renderInstallments(scoped, cmap);
  }


  function renderInstallments(txs, cmap) {
    const active = activeInstallments(txs);
    const totalRemaining = active.reduce((a, g) => a + g.remaining, 0);
    const el = $("#chart-installments");
    el.replaceChildren();
    if (!active.length) {
      $("#inst-sub").textContent = "Compras parceladas ainda em andamento";
      el.append(h("div", { class: "empty", style: "padding:24px 8px" }, h("div", { class: "big", text: "🎉" }), h("p", { text: "Nenhuma parcela em andamento." })));
      return;
    }
    $("#inst-sub").textContent = `${fmt(totalRemaining)} ainda a pagar em ${plural(active.length, "compra", "compras")}`;
    for (const g of active.slice(0, 6)) {
      const c = cmap[g.category];
      const row = h(
        "div",
        { class: "inst-row", tabindex: 0 },
        h("span", { class: "name", text: `${c ? c.icon + " " : ""}${g.name}` }),
        h("b", { class: "num", text: fmt(g.remaining) }),
        h("div", { class: "meter" }, h("div", { style: `width:${(g.k / g.n) * 100}%` })),
        h("span", { class: "meta", text: `${g.k} de ${g.n} pagas · faltam ${g.n - g.k} × ${fmt(g.amount)}` })
      );
      window.Charts.bindTooltip(row, () => ({
        title: g.name,
        rows: [
          { label: "Parcela", value: fmt(g.amount) },
          { label: "Pagas", value: `${g.k} de ${g.n}` },
          { label: "Falta pagar", value: fmt(g.remaining) },
        ],
      }));
      el.append(row);
    }
    if (active.length > 6) el.append(h("p", { class: "muted", style: "margin:0;font-size:13px", text: `e mais ${plural(active.length - 6, "compra", "compras")}` }));
  }

  /* ------------------------------------------------------------ transactions view */

  function renderTransactions() {
    const cmap = catMap();
    const catSel = $("#tx-cat");
    if (!catSel.options.length) {
      catSel.append(h("option", { value: "", text: "Todas as categorias" }), ...state.meta.categories.map((c) => h("option", { value: c.key, text: `${c.icon} ${c.label}` })));
    }
    const monthSel = $("#tx-month");
    const prevMonth = monthSel.value;
    const months = [...new Set(state.txs.map((t) => t.date.slice(0, 7)))].sort().reverse();
    monthSel.replaceChildren(h("option", { value: "", text: "Todos os meses" }), ...months.map((m) => h("option", { value: m, text: cap(monthLabel(m)) })));
    monthSel.value = months.includes(prevMonth) ? prevMonth : "";

    // Accent-insensitive text search; a value ("45,90") also finds entries of that amount.
    const raw = $("#tx-search").value.trim();
    const q = fold(raw);
    const qAmount = Math.abs(parseAmount(raw));
    const cat = catSel.value;
    const month = monthSel.value;
    const list = state.txs.filter(
      (t) =>
        (!cat || t.category === cat) &&
        (!month || t.date.startsWith(month)) &&
        (!q || fold(`${t.description} ${t.merchant} ${t.notes} ${t.source}`).includes(q) || Math.abs(t.amount_cents) === qAmount)
    );

    const container = $("#tx-container");
    container.replaceChildren();
    if (!state.txs.length) {
      container.append(h("div", { class: "card empty" }, h("div", { class: "big", text: "🧾" }), h("h3", { text: "Nenhum lançamento ainda" }), h("p", { text: "Use o botão “Novo gasto” ou importe uma fatura." })));
      return;
    }
    if (!list.length) {
      container.append(h("div", { class: "card empty" }, h("div", { class: "big", text: "🔍" }), h("p", { text: "Nada encontrado com esses filtros." })));
      return;
    }

    container.append(h("div", { class: "tx-summary" }, h("span", { text: plural(list.length, "lançamento", "lançamentos") }), h("b", { class: "num", text: fmt(sum(list)) })));

    const groups = {};
    for (const t of list) (groups[t.date.slice(0, 7)] ||= []).push(t);
    const fmtDay = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" });
    let shown = 0;
    for (const [m, txs] of Object.entries(groups).sort((a, b) => (a[0] < b[0] ? 1 : -1))) {
      if (shown >= state.txLimit) break;
      const visible = txs.slice(0, state.txLimit - shown);
      shown += visible.length;
      const rows = visible.map((t) => {
        const c = cmap[t.category] || cmap.outros;
        const meta = [fmtDay.format(parseDate(t.date)), c.label, t.origin === "fixed" && "🔁 fixo", t.source, t.installment && `parcela ${t.installment}`, t.notes].filter(Boolean).join(" · ");
        return h(
          "button",
          { class: "tx", type: "button", onclick: () => openTxModal(t) },
          h("span", { class: "cat-bubble", style: `--c:${catColor(c.key)}`, text: c.icon }),
          h(
            "span",
            { class: "tx-text" },
            h("span", { class: "tx-desc", text: t.merchant || t.description }),
            h("span", { class: "tx-meta", text: t.merchant && t.merchant !== t.description ? `${t.description} · ${meta}` : meta })
          ),
          h("span", { class: `tx-amount${t.amount_cents < 0 ? " credit" : ""}`, text: fmt(t.amount_cents) })
        );
      });
      container.append(
        h(
          "div",
          { class: "tx-month" },
          h("div", { class: "tx-month-head" }, h("span", { text: cap(monthLabel(m)) }), h("span", { class: "num", text: `${plural(txs.length, "lançamento", "lançamentos")} · ${fmt(sum(txs))}` })),
          h("div", { class: "card tx-list" }, rows)
        )
      );
    }
    if (shown < list.length) {
      container.append(
        h("button", {
          class: "btn more-btn",
          type: "button",
          text: `Mostrar mais (${list.length - shown} restantes)`,
          onclick: () => {
            state.txLimit += TX_PAGE;
            renderTransactions();
          },
        })
      );
    }
  }

  function refilterTransactions() {
    state.txLimit = TX_PAGE;
    renderTransactions();
  }

  /* ------------------------------------------------------------ transaction modal */

  function renderCatGrid() {
    $("#f-cats").replaceChildren(
      ...state.meta.categories.map((c) =>
        h(
          "button",
          {
            type: "button",
            class: "cat-option",
            style: `--c:${catColor(c.key)}`,
            "aria-pressed": String(state.formCat === c.key),
            onclick: () => {
              state.formCat = c.key;
              renderCatGrid();
              updateApplySimilar();
            },
          },
          h("span", { class: "ic", text: c.icon }),
          c.label
        )
      )
    );
  }

  // When an existing entry changes category, offer to fix the other entries from the same place.
  function updateApplySimilar() {
    const tx = state.editing;
    const changed = Boolean(tx && state.formCat !== tx.category);
    $("#f-learn-hint").hidden = !changed;
    const others = changed && state.similar ? state.similar.filter((s) => s.category !== state.formCat) : [];
    $("#f-apply-wrap").hidden = others.length === 0;
    if (others.length) {
      const c = catMap()[state.formCat];
      $("#f-apply-text").textContent = `Mudar também ${others.length === 1 ? "o outro lançamento" : `os outros ${others.length} lançamentos`} de “${tx.merchant || tx.description}” para ${c.label}`;
    }
  }

  function openTxModal(tx = null) {
    state.editing = tx;
    state.similar = null;
    $("#tx-dialog-title").textContent = tx ? "Editar lançamento" : "Novo gasto";
    $("#f-amount").value = tx ? amountInput(Math.abs(tx.amount_cents)) : "";
    $("#f-credit").checked = tx ? tx.amount_cents < 0 : false;
    $("#f-description").value = tx ? tx.description : "";
    $("#f-merchant").value = tx ? tx.merchant : "";
    $("#f-date").value = tx ? tx.date : iso(new Date());
    $("#f-source").value = tx ? tx.source : store.get("lastSource") || "";
    $("#f-installment").value = tx ? tx.installment || "" : "";
    $("#f-notes").value = tx ? tx.notes : "";
    $("#f-apply-similar").checked = true;
    state.formCat = tx ? tx.category : "mercado";
    $("#tx-delete").hidden = !tx;
    $("#tx-duplicate").hidden = !tx;
    $("#tx-error").hidden = true;
    renderCatGrid();
    updateApplySimilar();
    $("#tx-dialog").showModal();
    if (tx) {
      api(`/api/transactions/${tx.id}/similar`)
        .then((res) => {
          if (state.editing === tx) {
            state.similar = res.similar;
            updateApplySimilar();
          }
        })
        .catch(() => {});
    } else {
      setTimeout(() => $("#f-amount").focus(), 50);
    }
  }

  // Turns the open entry into a new one (handy for rent, bills and the next installment).
  function duplicateTx() {
    if (!state.editing) return;
    state.editing = null;
    state.similar = null;
    $("#tx-dialog-title").textContent = "Novo gasto (cópia)";
    $("#f-date").value = iso(new Date());
    const m = /^(\d+)\/(\d+)$/.exec($("#f-installment").value.trim());
    if (m && +m[1] < +m[2]) $("#f-installment").value = `${+m[1] + 1}/${m[2]}`;
    $("#tx-delete").hidden = true;
    $("#tx-duplicate").hidden = true;
    updateApplySimilar();
    $("#f-amount").focus();
  }

  async function saveTx(e) {
    e.preventDefault();
    const err = $("#tx-error");
    err.hidden = true;
    const fail = (msg) => {
      err.textContent = msg;
      err.hidden = false;
    };
    const cents = parseAmount($("#f-amount").value);
    if (!cents || isNaN(cents)) return fail("Informe um valor válido (ex.: 45,90).");
    const description = $("#f-description").value.trim();
    if (!description) return fail("Escreva uma descrição.");
    if (!$("#f-date").value) return fail("Escolha a data.");
    const installment = $("#f-installment").value.trim();
    if (installment && !/^\d+\s*\/\s*\d+$/.test(installment)) return fail("Parcela deve estar no formato 3/10.");
    const payload = {
      date: $("#f-date").value,
      description,
      merchant: $("#f-merchant").value.trim(),
      amount_cents: Math.abs(cents) * ($("#f-credit").checked ? -1 : 1),
      category: state.formCat,
      source: $("#f-source").value.trim(),
      installment: installment || null,
      notes: $("#f-notes").value.trim(),
    };
    const editing = state.editing;
    const applySimilar = Boolean(editing) && !$("#f-apply-wrap").hidden && $("#f-apply-similar").checked;
    $("#tx-save").disabled = true;
    try {
      let message = "Gasto adicionado ✨";
      if (editing) {
        const res = await api(`/api/transactions/${editing.id}${applySimilar ? "?apply_to_similar=true" : ""}`, jsonBody(payload, "PUT"));
        message = res.updated_similar ? `Atualizado, junto com mais ${plural(res.updated_similar, "lançamento", "lançamentos")}` : "Lançamento atualizado";
      } else {
        await api("/api/transactions", jsonBody(payload));
      }
      if (payload.source) store.set("lastSource", payload.source);
      $("#tx-dialog").close();
      toast(message);
      await Promise.all([loadTxs(), loadMeta()]);
      render();
    } catch (ex) {
      fail(ex.message);
    } finally {
      $("#tx-save").disabled = false;
    }
  }

  async function deleteTx() {
    if (!state.editing || !confirm("Excluir este lançamento?")) return;
    await api(`/api/transactions/${state.editing.id}`, { method: "DELETE" });
    $("#tx-dialog").close();
    toast("Lançamento excluído");
    await loadTxs();
    render();
  }

  /* ------------------------------------------------------------ import view */

  function renderFiles() {
    $("#file-chips").replaceChildren(
      ...state.files.map((f, i) =>
        h(
          "span",
          { class: "file-chip" },
          `${f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf") ? "📄" : "🖼️"} ${f.name}`,
          h("button", {
            type: "button",
            "aria-label": `Remover ${f.name}`,
            text: "✕",
            onclick: () => {
              state.files.splice(i, 1);
              renderFiles();
            },
          })
        )
      )
    );
    $("#upload-btn").disabled = state.files.length === 0;
  }

  function addFiles(list) {
    for (const f of list) state.files.push(f);
    $("#upload-error").hidden = true;
    renderFiles();
  }

  async function upload() {
    const btn = $("#upload-btn");
    const errEl = $("#upload-error");
    errEl.hidden = true;
    btn.disabled = true;
    const fd = new FormData();
    state.files.forEach((f) => fd.append("files", f, f.name));
    fd.append("source", $("#import-source").value.trim());
    fd.append("password", $("#import-password").value);
    try {
      const res = await api("/api/imports", { method: "POST", body: fd });
      state.lastUploadId = res.id;
      state.lastFiles = state.files;
      state.files = [];
      renderFiles();
      await loadImports();
      settleUpload();
      renderImport();
      if (state.imports.some((i) => i.status === "processing")) startPolling();
    } catch (ex) {
      errEl.textContent = ex.message;
      errEl.hidden = false;
      btn.disabled = false;
    }
  }

  // The free reader usually finishes before the first poll: report the outcome of the last
  // upload as soon as it is known. On error the files and password stay, ready to retry.
  function settleUpload() {
    const last = state.imports.find((i) => i.id === state.lastUploadId);
    if (!last || last.status === "processing") return false;
    if (last.status === "error") {
      $("#upload-error").textContent = last.error;
      $("#upload-error").hidden = false;
      state.files = state.lastFiles || [];
      renderFiles();
      if (/senha/i.test(last.error)) $("#import-password").focus();
    } else {
      $("#import-password").value = "";
      if (last.status === "review") toast("Fatura lida! Confira os lançamentos 👀");
    }
    state.lastUploadId = null;
    state.lastFiles = [];
    return true;
  }

  let pollTimer = null;
  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      try {
        const before = state.imports.filter((i) => i.status === "processing").map((i) => i.id);
        await loadImports();
        const changed = before.some((id) => state.imports.find((i) => i.id === id)?.status !== "processing");
        if (settleUpload() || changed) {
          if (state.view === "import") renderImport();
          if (changed) loadBank();
        }
        if (!state.imports.some((i) => i.status === "processing")) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
      } catch (_) {
        // Network hiccup: try again on the next tick.
      }
    }, 2500);
  }

  async function renderImport() {
    renderHistory();
    const pending = state.imports.filter((i) => i.status === "processing" || i.status === "review");
    const nodes = [];
    for (const imp of pending) {
      if (imp.status === "processing") {
        nodes.push(
          h(
            "div",
            { class: "card processing" },
            h("div", { class: "spinner" }),
            h(
              "div",
              {},
              h("b", { text: isBankSync(imp) ? "Buscando os gastos nos bancos…" : "Lendo a fatura…" }),
              h("div", {
                class: "muted",
                text: isBankSync(imp)
                  ? "Open Finance · costuma levar menos de um minuto. Pode sair desta tela."
                  : `${imp.filenames.join(", ")} · ${state.meta.reader === "claude" ? "costuma levar de 30 segundos a 2 minutos" : "leva poucos segundos"}. Pode sair desta tela.`,
              })
            )
          )
        );
      } else {
        try {
          nodes.push(await reviewCard(imp.id));
        } catch (_) {
          // Confirmed or discarded on the other phone meanwhile.
        }
      }
    }
    $("#pending-area").replaceChildren(...nodes);
  }

  async function reviewCard(id) {
    const detail = await api(`/api/imports/${id}`);
    const bank = detail.document_type === "open_finance";
    if (!state.review[id]) {
      state.review[id] = {
        source: detail.source || detail.issuer || "",
        rows: detail.transactions.map((t) => ({
          include: !t.possible_duplicate,
          date: t.date,
          description: t.description,
          merchant: t.merchant,
          category: t.category,
          initialCategory: t.category,
          fromRule: t.category_source === "rule",
          amount: amountInput(t.amount_cents),
          installment: t.installment,
          notes: t.notes,
          dup: t.possible_duplicate,
          source: t.source || "",
          external_id: t.external_id || null,
          bill_month: t.bill_month || null,
        })),
      };
    }
    const review = state.review[id];
    const rows = review.rows;
    const sourceInput = h("input", { class: "input", list: "sources-list", value: review.source, placeholder: "ex.: Nubank" });
    sourceInput.addEventListener("input", () => (review.source = sourceInput.value));

    const stats = h("div", { class: "review-stats" });
    // Double-check against the statement: what was read must add up to its printed total.
    const check = h("div", { class: "notice", style: "margin-bottom:16px" });
    const updateStats = () => {
      const included = rows.filter((r) => r.include);
      const total = included.reduce((a, r) => a + (parseAmount(r.amount) || 0), 0);
      const items = [
        h("div", {}, h("span", { text: "Selecionados" }), h("b", { text: `${included.length} de ${rows.length}` })),
        h("div", {}, h("span", { text: "Soma" }), h("b", { text: fmt(total) })),
      ];
      if (bank) {
        check.className = "notice";
        check.replaceChildren(h("b", { text: "Direto do banco: " }), "pagamentos de fatura, transferências entre contas e dinheiro recebido já ficaram de fora.");
      } else if (detail.statement_total_cents == null) {
        check.className = "notice";
        check.replaceChildren(h("b", { text: "Não achei o total da fatura para conferir. " }), "Compare a soma com o valor do PDF antes de importar.");
      } else {
        const allTotal = rows.reduce((a, r) => a + (parseAmount(r.amount) || 0), 0);
        const diff = allTotal - detail.statement_total_cents;
        const ok = Math.abs(diff) <= 1;
        check.className = ok ? "notice ok" : "notice error";
        check.replaceChildren(
          h("b", { text: ok ? "✓ Conferido: " : "⚠ A soma não bate com a fatura: " }),
          ok
            ? `os ${rows.length} lançamentos somam ${fmt(allTotal)}, exatamente o total da fatura.`
            : `os lançamentos somam ${fmt(allTotal)} e a fatura diz ${fmt(detail.statement_total_cents)} (${diff < 0 ? "faltam" : "sobram"} ${fmt(Math.abs(diff))}). Confira antes de importar.`
        );
        items.push(
          h(
            "div",
            {},
            h("span", { text: "Total impresso" }),
            h("b", { text: fmt(detail.statement_total_cents) }),
            Math.abs(diff) <= 1
              ? h("span", { class: "match-ok", text: "✓ bate com a soma de todos os lançamentos" })
              : h("span", { class: "match-bad", text: `Diferença de ${fmt(diff)}: confira (pode haver encargos ou saldo anterior)` })
          )
        );
      }
      stats.replaceChildren(...items);
    };
    const warnings = detail.warnings.filter((w) => !w.startsWith("A soma lida não bate"));
    updateStats();

    const catOptions = state.meta.categories.map((c) => [c.key, `${c.icon} ${c.label}`]);
    const catSelects = [];
    const trs = rows.map((r, idx) => {
      const tr = h("tr", { class: r.include ? "" : "off" });
      const check = h("input", { type: "checkbox", "aria-label": "Importar este lançamento" });
      check.checked = r.include;
      check.addEventListener("change", () => {
        r.include = check.checked;
        tr.className = r.include ? "" : "off";
        updateStats();
      });
      const dateIn = h("input", { class: "input dt", type: "date", value: r.date, required: true });
      dateIn.addEventListener("change", () => (r.date = dateIn.value));
      const descIn = h("input", { class: "input", value: r.merchant || r.description, title: r.description });
      descIn.addEventListener("input", () => (r.merchant = descIn.value));
      const catSel = h("select", { class: "input cat", "aria-label": "Categoria" }, catOptions.map(([k, l]) => h("option", { value: k, text: l })));
      catSel.value = r.category;
      catSelects[idx] = catSel;
      catSel.addEventListener("change", () => {
        const before = r.category;
        r.category = catSel.value;
        // The same place elsewhere in this statement follows the correction.
        const key = placeKey(r.merchant || r.description);
        let followed = 0;
        rows.forEach((o, j) => {
          if (o !== r && o.category === before && key && placeKey(o.merchant || o.description) === key) {
            o.category = r.category;
            catSelects[j].value = r.category;
            followed++;
          }
        });
        if (followed) toast(`Também mudei ${plural(followed, "lançamento igual", "lançamentos iguais")}`);
      });
      const amtIn = h("input", { class: "input amt", inputmode: "decimal", value: r.amount, "aria-label": "Valor" });
      amtIn.addEventListener("input", () => {
        r.amount = amtIn.value;
        updateStats();
      });
      const tags = [];
      if (r.fromRule) tags.push(h("span", { class: "tag rule", text: "categoria lembrada" }));
      if (r.installment) tags.push(h("span", { class: "tag info", text: `parcela ${r.installment}` }));
      if (parseAmount(r.amount) < 0) tags.push(h("span", { class: "tag info", text: "estorno/crédito" }));
      if (r.dup) tags.push(h("span", { class: "tag", text: `possível duplicado de “${r.dup}”` }));
      if (bank && r.source) tags.push(h("span", { class: "tag info", text: r.source }));
      if (r.notes) tags.push(h("span", { class: "tag info", text: r.notes }));
      tr.append(h("td", {}, check), h("td", {}, dateIn), h("td", { class: "desc-cell" }, descIn, tags.length ? h("div", {}, tags) : null), h("td", {}, catSel), h("td", {}, amtIn));
      return tr;
    });

    const errEl = h("div", { class: "notice error", hidden: true, style: "margin-top:12px" });
    const confirmBtn = h("button", { class: "btn btn-primary", type: "button" }, "✅ Importar selecionados");
    confirmBtn.addEventListener("click", async () => {
      errEl.hidden = true;
      const txs = [];
      const rowOf = [];
      for (const [i, r] of rows.entries()) {
        if (!r.include) continue;
        const cents = parseAmount(r.amount);
        const problem = !r.date ? "preencha a data" : !cents || isNaN(cents) ? "confira o valor" : null;
        if (problem) {
          errEl.textContent = `Linha ${i + 1}: ${problem}.`;
          errEl.hidden = false;
          return;
        }
        rowOf.push(i + 1);
        txs.push({
          date: r.date,
          description: r.description || r.merchant,
          merchant: r.merchant || "",
          amount_cents: cents,
          category: r.category,
          installment: r.installment,
          notes: r.notes || "",
          source: r.source || "",
          external_id: r.external_id,
          bill_month: r.bill_month,
          remember: r.category !== r.initialCategory,
        });
      }
      if (!txs.length) {
        errEl.textContent = "Nenhum lançamento selecionado. Para não importar nada, use Descartar.";
        errEl.hidden = false;
        return;
      }
      confirmBtn.disabled = true;
      try {
        const res = await api(`/api/imports/${id}/confirm`, jsonBody({ source: review.source.trim(), transactions: txs }));
        delete state.review[id];
        toast(`${plural(res.imported, "lançamento importado", "lançamentos importados")} 🎉`);
        await Promise.all([loadTxs(), loadImports(), loadMeta()]);
        renderImport();
      } catch (ex) {
        if (ex.status === 409 || ex.status === 404) {
          toast(ex.message);
          delete state.review[id];
          await Promise.all([loadTxs(), loadImports()]);
          renderImport();
          return;
        }
        errEl.textContent = validationText(ex.body?.detail, (j) => rowOf[j]) || ex.message;
        errEl.hidden = false;
        confirmBtn.disabled = false;
      }
    });
    const discardBtn = h("button", { class: "btn btn-ghost btn-danger", type: "button" }, rows.length ? "Descartar" : "Descartar leitura");
    discardBtn.addEventListener(
      "click",
      safely(async () => {
        if (rows.length && !confirm("Descartar esta leitura? Nada será importado.")) return;
        await api(`/api/imports/${id}`, { method: "DELETE" });
        delete state.review[id];
        await loadImports();
        renderImport();
      })
    );

    const titleBits = [
      detail.issuer,
      detail.reference_month && cap(monthLabel(detail.reference_month)),
      detail.due_date && `vence ${parseDate(detail.due_date).toLocaleDateString("pt-BR")}`,
    ].filter(Boolean);

    return h(
      "div",
      { class: "card" },
      h(
        "div",
        { class: "card-head" },
        h(
          "div",
          {},
          h("h2", { class: "card-title", text: `👀 Revisar: ${titleBits[0] || detail.filenames.join(", ")}` }),
          h("p", { class: "card-sub", text: bank ? "Gastos novos vindos do Open Finance" : titleBits.slice(1).join(" · ") || detail.filenames.join(", ") })
        )
      ),
      rows.length && rows.every((r) => r.dup)
        ? h("div", { class: "notice", style: "margin-bottom:16px" }, h("b", { text: "Parece que esta fatura já foi importada: " }), "todos os lançamentos já existem com a mesma data e valor. Se for o caso, é só descartar.")
        : null,
      check,
      warnings.length ? h("div", { class: "notice", style: "margin-bottom:16px" }, h("b", { text: "Atenção:" }), h("ul", {}, warnings.map((w) => h("li", { text: w })))) : null,
      h("div", { class: "review-head" }, stats, bank ? null : h("label", { class: "field", style: "min-width:200px" }, h("span", { text: "Cartão / conta" }), sourceInput)),
      rows.length
        ? h(
            "div",
            { class: "table-scroll" },
            h(
              "table",
              { class: "review-table" },
              h("thead", {}, h("tr", {}, h("th", {}), h("th", { text: "Data" }), h("th", { text: "Descrição" }), h("th", { text: "Categoria" }), h("th", { text: "Valor (R$)", style: "text-align:right" }))),
              h("tbody", {}, trs)
            )
          )
        : h("p", { class: "muted", text: "Nenhum lançamento encontrado neste documento." }),
      errEl,
      h("div", { class: "review-actions" }, discardBtn, rows.length ? confirmBtn : null)
    );
  }

  /* ------------------------------------------------------------ fixed expenses */

  async function loadFixed() {
    state.fixed = await api("/api/fixed");
    renderFixed();
  }

  function renderFixed() {
    const cmap = catMap();
    const sel = $("#fx-cat");
    if (!sel.options.length) sel.append(...state.meta.categories.map((c) => h("option", { value: c.key, text: `${c.icon} ${c.label}` })));
    if (!state.editingFixed && !$("#fx-start").value) resetFixedForm();
    const current = monthKey(today());
    const active = state.fixed.filter((f) => f.start_month <= current && (!f.end_month || f.end_month >= current));
    $("#fixed-sub").textContent = state.fixed.length
      ? `${fmt(sum(active))} por mês em ${plural(active.length, "gasto fixo ativo", "gastos fixos ativos")}`
      : "Entram como lançamento em cada mês; dá para editar um mês específico em Lançamentos.";
    const short = (m) => `${MONTHS_SHORT[+m.slice(5, 7) - 1]}/${m.slice(0, 4)}`;
    $("#fixed-list").replaceChildren(
      ...(state.fixed.length
        ? state.fixed.map((f) => {
            const c = cmap[f.category] || cmap.outros;
            const ended = f.end_month && f.end_month < current;
            const meta = [
              c.label,
              `todo dia ${f.day}`,
              `desde ${short(f.start_month)}`,
              f.end_month && `até ${short(f.end_month)}`,
              f.source,
              ended && "encerrado",
            ].filter(Boolean);
            const edit = h("button", { class: "btn btn-sm btn-ghost", type: "button", text: "Editar", onclick: () => editFixed(f) });
            const del = h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", text: "Excluir", onclick: safely(() => deleteFixed(f)) });
            return h(
              "div",
              { class: "history-row fixed-row", style: ended ? "opacity:.6" : "" },
              h("span", { class: "cat-bubble", style: `--c:${catColor(c.key)}`, text: c.icon }),
              h("div", { style: "min-width:0" }, h("div", { class: "title", text: f.description }), h("div", { class: "meta", text: meta.join(" · ") })),
              h("b", { class: "num", text: fmt(f.amount_cents) }),
              h("div", { class: "fixed-actions" }, edit, del)
            );
          })
        : [h("p", { class: "muted", text: "Nenhum gasto fixo ainda. Cadastre aluguel, condomínio, internet, plano de saúde… ao lado." })])
    );
  }

  function resetFixedForm() {
    state.editingFixed = null;
    $("#fixed-form").reset();
    $("#fx-cat").value = "casa";
    $("#fx-day").value = 5;
    $("#fx-start").value = monthKey(today());
    $("#fixed-form-title").textContent = "Novo gasto fixo";
    $("#fixed-cancel").hidden = true;
    $("#fx-past-wrap").hidden = true;
    $("#fixed-error").hidden = true;
  }

  function editFixed(f) {
    state.editingFixed = f;
    $("#fx-desc").value = f.description;
    $("#fx-amount").value = amountInput(f.amount_cents);
    $("#fx-cat").value = f.category;
    $("#fx-day").value = f.day;
    $("#fx-source").value = f.source;
    $("#fx-start").value = f.start_month;
    $("#fx-end").value = f.end_month || "";
    $("#fx-past").checked = false;
    $("#fx-past-wrap").hidden = false;
    $("#fixed-form-title").textContent = `Editar: ${f.description}`;
    $("#fixed-cancel").hidden = false;
    $("#fixed-error").hidden = true;
    $("#fx-desc").scrollIntoView({ behavior: "smooth", block: "center" });
    $("#fx-desc").focus({ preventScroll: true });
  }

  async function saveFixed(e) {
    e.preventDefault();
    const errEl = $("#fixed-error");
    errEl.hidden = true;
    const cents = parseAmount($("#fx-amount").value);
    if (!cents || isNaN(cents) || cents < 0) {
      errEl.textContent = "Informe um valor válido (ex.: 3.200,00).";
      errEl.hidden = false;
      return;
    }
    const payload = {
      description: $("#fx-desc").value.trim(),
      amount_cents: cents,
      category: $("#fx-cat").value,
      day: +$("#fx-day").value,
      start_month: $("#fx-start").value,
      end_month: $("#fx-end").value || null,
      source: $("#fx-source").value.trim(),
    };
    const editing = state.editingFixed;
    const btn = $("#fixed-save");
    btn.disabled = true;
    try {
      if (editing) {
        const past = $("#fx-past").checked ? "?apply_to_past=true" : "";
        await api(`/api/fixed/${editing.id}${past}`, jsonBody(payload, "PUT"));
        toast("Gasto fixo atualizado");
      } else {
        const res = await api("/api/fixed", jsonBody(payload));
        toast(res.created_entries ? `Gasto fixo criado e lançado em ${plural(res.created_entries, "mês", "meses")} 🔁` : "Gasto fixo criado: entra quando o mês chegar 🔁");
      }
      resetFixedForm();
      await Promise.all([loadFixed(), loadTxs()]);
    } catch (ex) {
      errEl.textContent = validationText(ex.body?.detail) || ex.message;
      errEl.hidden = false;
    } finally {
      btn.disabled = false;
    }
  }

  async function deleteFixed(f) {
    if (!confirm(`Parar o gasto fixo “${f.description}”? Ele deixa de entrar nos próximos meses.`)) return;
    const removeAll = confirm("Apagar também os lançamentos dos meses que já passaram?\n\nOK = apagar tudo · Cancelar = manter o que já foi lançado");
    await api(`/api/fixed/${f.id}${removeAll ? "?remove_entries=true" : ""}`, { method: "DELETE" });
    if (state.editingFixed?.id === f.id) resetFixedForm();
    toast("Gasto fixo removido");
    await Promise.all([loadFixed(), loadTxs()]);
  }

  /* ------------------------------------------------------------ bank sync (Open Finance) */

  const isBankSync = (imp) => imp.filenames.length === 1 && imp.filenames[0] === "Open Finance";

  const BANK_STATUS = {
    UPDATED: ["✓ atualizado", "match-ok"],
    UPDATING: ["atualizando…", ""],
    LOGIN_ERROR: ["⚠ reconecte no meu.pluggy.ai", "match-bad"],
    OUTDATED: ["⚠ desatualizado: reconecte no meu.pluggy.ai", "match-bad"],
    WAITING_USER_INPUT: ["⚠ aguardando você no meu.pluggy.ai", "match-bad"],
  };

  async function loadBank(check = false) {
    try {
      const prev = state.bank;
      state.bank = await api(`/api/bank${check ? "?check=true" : ""}`);
      // Without checking, keep the bank names and statuses already known.
      if (!check && prev?.items.length && !state.bank.items.length) state.bank.items = prev.items;
    } catch (_) {
      state.bank = null;
    }
    renderBank();
  }

  function renderBank() {
    const b = state.bank;
    const el = $("#bank-status");
    const errEl = $("#bank-error");
    if (!b) return;
    $("#bank-sync-btn").hidden = !b.configured;
    $("#bank-edit-btn").textContent = b.configured ? "⚙️ Configurar" : "🔗 Conectar bancos";
    errEl.hidden = !b.error;
    errEl.textContent = b.error || "";
    if (!b.configured) {
      el.replaceChildren(
        h("p", { class: "muted", text: "Ainda não configurado. Clique em Conectar bancos e cole o Client ID, o Client Secret e os Item IDs do dashboard.pluggy.ai." })
      );
      return;
    }
    const items = b.items.length
      ? b.items.map((it) => {
          const [label, cls] = BANK_STATUS[it.status] || [it.status.toLowerCase(), ""];
          return h("li", {}, h("b", { text: it.bank }), " ", h("span", { class: cls, text: label }));
        })
      : b.item_ids.map((id) => h("li", { class: "muted", text: `Conexão ${id.slice(0, 8)}…` }));
    el.replaceChildren(
      h("ul", { class: "bank-list" }, items),
      h("p", {
        class: "muted",
        text: b.last_sync
          ? `Última sincronização: ${new Date(b.last_sync).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}. A próxima traz só o que for novo.`
          : "Ainda não sincronizado. A primeira vez traz os últimos 90 dias.",
      })
    );
  }

  function toggleBankForm(show) {
    const form = $("#bank-form");
    form.hidden = !show;
    if (!show) return;
    const b = state.bank || {};
    $("#bank-client-id").value = "";
    $("#bank-client-id").placeholder = b.client_id || "";
    $("#bank-client-id").required = !b.client_id;
    $("#bank-client-secret").value = "";
    $("#bank-client-secret").placeholder = b.has_secret ? "•••••• (deixe vazio para manter)" : "";
    $("#bank-items").value = (b.item_ids || []).join("\n");
    $("#bank-client-id").focus();
  }

  async function saveBank(e) {
    e.preventDefault();
    const btn = $("#bank-save-btn");
    const errEl = $("#bank-error");
    errEl.hidden = true;
    btn.disabled = true;
    btn.textContent = "Testando…";
    try {
      const res = await api(
        "/api/bank/config",
        jsonBody({
          // Empty Client ID / Secret keep the saved ones.
          client_id: $("#bank-client-id").value.trim(),
          client_secret: $("#bank-client-secret").value.trim(),
          item_ids: $("#bank-items").value,
        })
      );
      toast(`Conectado: ${res.items.map((i) => i.bank).join(" + ")} 🎉`);
      toggleBankForm(false);
      state.bank = null;
      await loadBank();
      state.bank.items = res.items;
      renderBank();
    } catch (ex) {
      errEl.textContent = validationText(ex.body?.detail) || ex.message;
      errEl.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = "💾 Testar e salvar";
    }
  }

  async function syncBank() {
    const btn = $("#bank-sync-btn");
    $("#bank-error").hidden = true;
    btn.disabled = true;
    try {
      await api("/api/bank/sync", { method: "POST" });
      await loadImports();
      renderImport();
      startPolling();
    } catch (ex) {
      $("#bank-error").textContent = ex.message;
      $("#bank-error").hidden = false;
    } finally {
      btn.disabled = false;
    }
  }

  function renderHistory() {
    const el = $("#history");
    const done = state.imports.filter((i) => i.status === "confirmed" || i.status === "error");
    if (!done.length) {
      el.replaceChildren(h("p", { class: "muted", text: "Nenhuma importação ainda." }));
      return;
    }
    const statusText = { confirmed: "importada", error: "erro", review: "revisar", processing: "lendo" };
    el.replaceChildren(
      ...done.map((imp) => {
        const meta = [
          imp.reference_month && cap(monthLabel(imp.reference_month)),
          imp.status === "confirmed" ? `${imp.transaction_count} lidos` : imp.error,
          imp.source,
          new Date(imp.created_at.replace(" ", "T")).toLocaleDateString("pt-BR"),
          imp.cost_usd != null && `custo ≈ US$ ${imp.cost_usd.toFixed(2).replace(".", ",")}`,
        ].filter(Boolean);
        const del = h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", text: "Excluir" });
        del.addEventListener(
          "click",
          safely(async () => {
            const msg = imp.status === "confirmed" ? "Excluir esta importação e todos os lançamentos que vieram dela?" : "Remover este registro?";
            if (!confirm(msg)) return;
            await api(`/api/imports/${imp.id}`, { method: "DELETE" });
            toast("Importação excluída");
            await Promise.all([loadTxs(), loadImports()]);
            renderImport();
          })
        );
        return h(
          "div",
          { class: "history-row" },
          h(
            "div",
            { style: "min-width:0" },
            h("div", { class: "title" }, h("span", { class: `status ${imp.status}`, text: statusText[imp.status] }), " ", imp.issuer || imp.filenames.join(", ")),
            h("div", { class: "meta", text: meta.join(" · ") })
          ),
          del
        );
      })
    );
  }

  /* ------------------------------------------------------------ theme */

  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

  function applyTheme(theme) {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }

  // Toggles light/dark; choosing what the system already uses goes back to following it.
  function toggleTheme() {
    const dark = getComputedStyle(document.documentElement).colorScheme === "dark";
    const next = dark ? "light" : "dark";
    const followSystem = (next === "dark") === darkQuery.matches;
    store.set("theme", followSystem ? null : next);
    applyTheme(followSystem ? null : next);
    render();
  }

  /* ------------------------------------------------------------ boot */

  function bind() {
    document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setView(t.dataset.view)));
    document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.goto)));
    document.querySelectorAll('[data-action="new-tx"]').forEach((b) => b.addEventListener("click", () => openTxModal()));
    const dialog = $("#tx-dialog");
    document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
    dialog.addEventListener("click", (e) => e.target === dialog && dialog.close()); // backdrop
    $("#tx-form").addEventListener("submit", saveTx);
    $("#tx-delete").addEventListener("click", safely(deleteTx));
    $("#tx-duplicate").addEventListener("click", duplicateTx);
    $("#theme-btn").addEventListener("click", toggleTheme);
    darkQuery.addEventListener("change", () => !store.get("theme") && render());

    $("#month-select").addEventListener("change", (e) => e.target.value && choosePeriod("month", e.target.value));
    $("#source-select").addEventListener("change", (e) => {
      state.source = e.target.value;
      renderDashboard();
    });

    $("#tx-search").addEventListener("input", refilterTransactions);
    $("#tx-cat").addEventListener("change", refilterTransactions);
    $("#tx-month").addEventListener("change", refilterTransactions);

    const dz = $("#dropzone");
    const fi = $("#file-input");
    fi.addEventListener("change", () => {
      addFiles(fi.files);
      fi.value = "";
    });
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("over");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("over"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("over");
      addFiles(e.dataTransfer.files);
    });
    $("#upload-btn").addEventListener("click", upload);
    $("#bank-edit-btn").addEventListener("click", () => toggleBankForm($("#bank-form").hidden));
    $("#bank-form").addEventListener("submit", saveBank);
    $("#bank-sync-btn").addEventListener("click", syncBank);
    $("#fixed-form").addEventListener("submit", saveFixed);
    $("#fixed-cancel").addEventListener("click", resetFixedForm);

    let resizeTimer;
    let lastWidth = window.innerWidth;
    window.addEventListener("resize", () => {
      if (window.innerWidth === lastWidth) return;
      lastWidth = window.innerWidth;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => state.view === "dashboard" && renderDashboard(), 150);
    });
    window.addEventListener("hashchange", () => {
      const v = location.hash.slice(1);
      if (VIEWS.includes(v) && v !== state.view) setView(v);
    });
    window.addEventListener("scroll", () => window.Charts.tooltip.hide(), { passive: true });

    // Two people use the app: coming back to it picks up what the other one changed.
    document.addEventListener(
      "visibilitychange",
      safely(async () => {
        if (document.visibilityState !== "visible") return;
        await Promise.all([loadTxs(), loadImports()]);
        if (!dialog.open) render();
        if (state.imports.some((i) => i.status === "processing")) startPolling();
      })
    );
  }

  async function boot() {
    applyTheme(store.get("theme"));
    state.basis = store.get("basis") === "purchase" ? "purchase" : "bill";
    bind();
    await Promise.all([loadMeta(), loadTxs(), loadImports()]);
    if (state.imports.some((i) => i.status === "processing")) startPolling();
    const v = location.hash.slice(1);
    setView(VIEWS.includes(v) ? v : "dashboard");
  }

  boot().catch((e) => {
    document.querySelector("main").prepend(h("div", { class: "notice error", text: `Não consegui carregar os dados: ${e.message}` }));
  });
})();
