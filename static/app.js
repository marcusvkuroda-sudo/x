/* Controle dos Tolinos — frontend */
(function () {
  const { fmt, fmtCompact, h, iso } = window.Charts;
  const Logic = window.Logic;
  const { fold, placeKey, parseAmount, amountInput, activeInstallments } = Logic;

  const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

  const TX_PAGE = 150;
  const VIEWS = ["dashboard", "transactions", "plan", "import"];

  const state = {
    meta: { categories: [], sources: [] },
    txs: [],
    imports: [],
    view: "dashboard",
    month: null, // YYYY-MM shown in the dashboard (statement month)
    focus: null, // { kind, source? }: what the detail cards show
    cat: null,
    files: [],
    review: {}, // import id -> { source, rows }
    lastUploadId: null,
    lastFiles: [],
    editing: null,
    formCat: "mercado",
    similar: null, // transactions from the same place as the one being edited
    txLimit: TX_PAGE,
    bank: null, // Open Finance settings (never includes the secret)
    fixed: [],
    editingFixed: null,
    incomes: [],
    editingIncome: null,
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
    if (view === "plan") safely(loadPlan)();
  }

  function render() {
    if (state.view === "dashboard") renderDashboard();
    else if (state.view === "transactions") renderTransactions();
    else if (state.view === "plan") renderPlan();
    else renderImport();
  }

  /* ------------------------------------------------------------ month */

  const monthOf = Logic.monthOf;
  // Kinds of money, in the fixed order of the validated palette (blue, orange, aqua, gray).
  const KINDS = {
    credito: { label: "Cartões de crédito", short: "Crédito", icon: "💳", color: "var(--kind-credito)" },
    debito: { label: "Débito", short: "Débito", icon: "🏧", color: "var(--kind-debito)" },
    fixo: { label: "Gastos fixos", short: "Fixos", icon: "🔁", color: "var(--kind-fixo)" },
    outros: { label: "Lançados à mão", short: "Outros", icon: "✍️", color: "var(--kind-outros)" },
  };
  const currentMonth = () => monthKey(today());
  const shortMonth = (m) => `${MONTHS_SHORT[+m.slice(5, 7) - 1]}/${m.slice(2, 4)}`;
  const shortDate = (d) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;

  // From the first month with data to the last bill already showing up (at least next month,
  // where the open card bill usually goes).
  function monthRange() {
    const cur = currentMonth();
    // A bad date from a bank ("0001-01") must not stretch the list over centuries.
    const withData = state.txs.map(monthOf).filter((m) => m >= Logic.addMonths(cur, -60) && m <= Logic.addMonths(cur, 12));
    const first = [cur, ...withData].sort()[0];
    const last = [Logic.addMonths(cur, 1), ...withData].sort().pop();
    const out = [];
    for (let m = first; m <= last; m = Logic.addMonths(m, 1)) out.push(m);
    return out;
  }

  function chooseMonth(month) {
    state.month = month;
    renderDashboard();
  }

  function whenLabel(month) {
    const d = Logic.monthDiff(currentMonth(), month);
    if (d === 0) return "mês atual";
    if (d === 1) return "próximo mês · previsão";
    if (d === -1) return "mês passado";
    return d > 0 ? `daqui a ${d} meses · previsão` : `há ${-d} meses`;
  }

  const summaryOf = (month) =>
    Logic.monthSummary(state.txs, month, { today: today(), cards: state.meta.cards || {}, fixed: state.fixed, incomes: state.incomes });

  function renderMonthNav() {
    const months = monthRange();
    if (!state.month || !months.includes(state.month)) state.month = months.includes(currentMonth()) ? currentMonth() : months[months.length - 1];
    const i = months.indexOf(state.month);
    $("#month-title").textContent = cap(monthLabel(state.month));
    $("#month-when").textContent = whenLabel(state.month);
    $("#month-prev").disabled = i <= 0;
    $("#month-next").disabled = i >= months.length - 1;
    const strip = $("#month-strip");
    strip.replaceChildren(
      ...months.map((m) => {
        const s = summaryOf(m);
        return h(
          "button",
          {
            type: "button",
            role: "tab",
            class: `month-chip${m === state.month ? " on" : ""}${m === currentMonth() ? " now" : ""}`,
            "aria-selected": String(m === state.month),
            title: `${cap(monthLabel(m))}: ${fmt(s.projected)}`,
            onclick: () => chooseMonth(m),
          },
          h("b", { text: shortMonth(m) }),
          h("span", { class: "num", text: s.projected ? fmtCompact(s.projected) : "–" })
        );
      })
    );
    const on = strip.querySelector(".on");
    if (on) strip.scrollLeft = on.offsetLeft - strip.clientWidth / 2 + on.offsetWidth / 2;
  }

  /* ------------------------------------------------------------ dashboard */

  // What the detail cards show: everything, one kind (credit, debit...) or one card / account.
  const inFocus = (t) => {
    const f = state.focus;
    if (!f) return true;
    const kind = Logic.kindOf(t);
    return kind === f.kind && (!f.source || f.kind === "fixo" || t.source === f.source);
  };

  function setFocus(f) {
    const same = state.focus && f && state.focus.kind === f.kind && (state.focus.source || "") === (f.source || "");
    state.focus = same ? null : f;
    renderDashboard();
  }

  function setCat(key) {
    state.cat = state.cat === key ? null : key;
    renderDashboard();
  }

  function focusLabel(f) {
    if (!f) return "";
    const K = KINDS[f.kind];
    return f.source && f.kind !== "fixo" ? `${K.icon} ${Logic.accountName(f.source) || f.source} · ${K.short.toLowerCase()}` : `${K.icon} ${K.label}`;
  }

  function renderDashboard() {
    const empty = !state.txs.length && !state.fixed.length && !state.incomes.length;
    $("#dash-empty").hidden = !empty;
    $("#dash").hidden = empty;
    renderMonthNav();
    if (empty) return;
    const s = summaryOf(state.month);
    renderBudget(s);
    renderAccounts(s);
    renderFocusBar();
    const scoped = state.txs.filter(inFocus);
    const ofMonth = (txs, m) => txs.filter((t) => monthOf(t) === m);
    renderCategories(ofMonth(scoped, state.month), ofMonth(scoped, Logic.addMonths(state.month, -1)));
    const byCat = state.cat ? scoped.filter((t) => t.category === state.cat) : scoped;
    renderMerchants(ofMonth(byCat, state.month));
    renderMonthly(byCat);
    renderInstallments(byCat, catMap());
  }

  // Income x expenses -> what is left, with the projection to the end of the month.
  function renderBudget(s) {
    const el = $("#budget");
    const past = s.when === "past";
    const future = s.when === "future";
    const extra = s.projected - s.spent;
    const left = past ? s.left : s.leftProjected;
    const kinds = s.groups.map((g) =>
      h(
        "button",
        { type: "button", class: "kind-pill", onclick: () => setFocus({ kind: g.kind }) },
        h("i", { style: `background:${KINDS[g.kind].color}` }),
        h("span", { text: KINDS[g.kind].short }),
        h("b", { class: "num", text: fmt(past ? g.total : g.projected) })
      )
    );
    const max = Math.max(s.income, s.projected, 1);
    const pct = (v) => `${Math.max(0, (v / max) * 100)}%`;
    const meter = h(
      "div",
      { class: "budget-meter", role: "img", "aria-label": `Despesas ${fmt(s.projected)} de uma renda de ${fmt(s.income)}` },
      h("div", { class: "meter-spent", style: `width:${pct(s.spent)}` }),
      extra > 0 && !past ? h("div", { class: "meter-extra", style: `width:${pct(extra)}` }) : null,
      s.income ? h("div", { class: "meter-income", style: `left:${pct(s.income)}` }) : null
    );
    window.Charts.bindTooltip(meter, () => ({
      title: cap(monthLabel(s.month)),
      rows: [
        { label: "Renda", value: fmt(s.income) },
        { color: "var(--seq-4)", label: "Já lançado", value: fmt(s.spent) },
        ...(extra > 0 && !past ? [{ color: "var(--seq-2)", label: "Previsto até o fim", value: fmt(extra) }] : []),
      ],
      total: { label: past ? "Sobrou" : "Deve sobrar", value: fmt(left) },
    }));

    if (!s.income) {
      el.replaceChildren(
        h("div", { class: "budget-hero" }, h("span", { class: "budget-label", text: past ? "Gastamos no mês" : "Despesas previstas no mês" }), h("b", { class: "hero-num num", text: fmt(past ? s.spent : s.projected) }), extra > 0 && !past ? h("small", { text: `${fmt(s.spent)} já lançados` }) : null),
        h("div", { class: "notice", style: "margin:4px 0 16px" }, h("b", { text: "Quanto sobra? " }), "Cadastre a renda de vocês em ", h("a", { href: "#plan", text: "🎯 Planejar" }), " e o painel mostra o disponível do mês."),
        h("div", { class: "kind-pills" }, kinds)
      );
      return;
    }
    const ok = left >= 0;
    el.replaceChildren(
      h(
        "div",
        { class: "budget-hero" },
        h("span", { class: "budget-label", text: past ? "Sobrou no mês" : future ? "Deve sobrar no mês" : "Disponível até o fim do mês" }),
        h("b", { class: `hero-num num ${ok ? "good" : "bad"}`, text: fmt(left) }),
        h("small", { class: ok ? "good" : "bad", text: ok ? `✓ ${Math.round((left / s.income) * 100)}% da renda` : `⚠ faltam ${fmt(-left)} para fechar o mês` })
      ),
      h(
        "div",
        { class: "budget-stats" },
        h("div", {}, h("span", { text: "Renda" }), h("b", { class: "num", text: fmt(s.income) }), h("small", { text: plural(s.incomes.length, "entrada", "entradas") })),
        h("div", {}, h("span", { text: past ? "Despesas" : "Despesas previstas" }), h("b", { class: "num", text: fmt(past ? s.spent : s.projected) }), h("small", { text: past ? "faturas, débito e fixos" : "faturas + débito + fixos" })),
        h("div", {}, h("span", { text: "Já lançado" }), h("b", { class: "num", text: fmt(s.spent) }), h("small", { text: past || !extra ? "tudo lançado" : `+ ${fmt(extra)} previsto` }))
      ),
      meter,
      h(
        "div",
        { class: "meter-legend" },
        h("span", {}, h("i", { style: "background:var(--seq-4)" }), "já lançado"),
        extra > 0 && !past ? h("span", {}, h("i", { class: "hatch" }), "previsto até o fim do mês") : null,
        h("span", {}, h("i", { class: "tick" }), "renda")
      ),
      h("div", { class: "kind-pills" }, kinds)
    );
  }

  function billText(a) {
    const b = a.bill;
    if (!b) return a.kind === "credito" ? "fatura" : "";
    if (b.state === "closed") return iso(today()) > b.due ? `fatura fechada · venceu ${shortDate(b.due)}` : `fatura fechada · vence ${shortDate(b.due)}`;
    if (b.state === "open") return `fatura aberta · fecha ${shortDate(b.closes)} · vence ${shortDate(b.due)}`;
    return `abre ${shortDate(b.opens)} · vence ${shortDate(b.due)}`;
  }

  function renderAccounts(s) {
    const el = $("#accounts");
    if (!s.groups.length) {
      el.replaceChildren(h("p", { class: "muted", text: "Nada lançado neste mês ainda." }));
      return;
    }
    const f = state.focus;
    el.replaceChildren(
      ...s.groups.map((g) => {
        const K = KINDS[g.kind];
        const groupOn = f && f.kind === g.kind && !f.source;
        const head = h(
          "button",
          { type: "button", class: `acc-head${groupOn ? " on" : ""}`, "aria-pressed": String(Boolean(groupOn)), onclick: () => setFocus({ kind: g.kind }) },
          h("i", { class: "kind-dot", style: `background:${K.color}` }),
          h("span", { text: `${K.icon} ${K.label}` }),
          h("b", { class: "num", text: fmt(s.when === "past" ? g.total : g.projected) })
        );
        let rows;
        if (g.kind === "fixo") {
          const items = g.accounts.flatMap((a) => a.items);
          rows = items.map((it) => h("div", { class: "acc-row static" }, h("span", { class: "acc-name", text: it.name }), h("span", { class: "acc-meta", text: it.planned ? "previsto" : "lançado" }), h("b", { class: "num", text: fmt(it.amount) })));
        } else {
          rows = g.accounts.map((a) => {
            const on = f && f.kind === a.kind && f.source === a.source;
            const meta = [a.kind === "credito" ? billText(a) : a.kind === "debito" ? (s.when === "current" ? "até hoje" : "") : "lançamentos manuais"];
            if (a.projected > a.total && s.when !== "past") meta.push(`previsto ${fmt(a.projected)}`);
            const projectedOnly = !a.total && a.projected;
            return h(
              "button",
              { type: "button", class: `acc-row${on ? " on" : ""}`, "aria-pressed": String(Boolean(on)), onclick: () => setFocus({ kind: a.kind, source: a.source }) },
              h("span", { class: "acc-name", text: a.name || (a.kind === "outros" ? "Sem cartão" : a.source || "Sem nome") }),
              h("span", { class: "acc-meta", text: meta.filter(Boolean).join(" · ") }),
              h("b", { class: `num${projectedOnly ? " muted" : ""}`, text: fmt(projectedOnly ? a.projected : a.total) })
            );
          });
        }
        return h("div", { class: "acc-group" }, head, rows);
      })
    );
  }

  function renderFocusBar() {
    const bar = $("#focus-bar");
    const parts = [];
    if (state.focus) parts.push(h("button", { type: "button", class: "chip on", onclick: () => setFocus(null) }, `${focusLabel(state.focus)} ✕`));
    if (state.cat) {
      const c = catMap()[state.cat];
      if (c) parts.push(h("button", { type: "button", class: "chip on", onclick: () => setCat(state.cat) }, `${c.icon} ${c.label} ✕`));
    }
    bar.hidden = !parts.length;
    if (parts.length)
      bar.replaceChildren(
        h("span", { class: "muted", text: "Mostrando só:" }),
        ...parts,
        h("button", { type: "button", class: "btn btn-sm btn-ghost", text: "Ver tudo", onclick: () => { state.focus = null; state.cat = null; renderDashboard(); } })
      );
  }

  function deltaText(current, previous) {
    if (!previous) return current > 0 ? { text: "novo", cls: "up" } : null;
    const pct = Math.round(((current - previous) / Math.abs(previous)) * 100);
    if (pct === 0) return { text: "= igual", cls: "" };
    return { text: `${pct > 0 ? "▲" : "▼"} ${Math.abs(pct)}%`, cls: pct > 0 ? "up" : "down" };
  }

  function renderCategories(txs, prevTxs) {
    const cats = state.meta.categories;
    const byCat = {};
    const countCat = {};
    for (const t of txs) {
      byCat[t.category] = (byCat[t.category] || 0) + t.amount_cents;
      countCat[t.category] = (countCat[t.category] || 0) + 1;
    }
    const byCatPrev = {};
    for (const t of prevTxs) byCatPrev[t.category] = (byCatPrev[t.category] || 0) + t.amount_cents;
    const compare = Object.keys(byCatPrev).length > 0;
    const catTotal = Object.values(byCat).reduce((a, b) => a + Math.max(0, b), 0);
    const ranked = cats.filter((c) => byCat[c.key] > 0).sort((a, b) => byCat[b.key] - byCat[a.key]);
    const prevName = MONTHS[+Logic.addMonths(state.month, -1).slice(5, 7) - 1];
    $("#compo").replaceChildren(
      ...ranked.map((c) => {
        const seg = h("div", { style: `flex:${byCat[c.key]};background:${catColor(c.key)}`, tabindex: 0 });
        window.Charts.bindTooltip(seg, () => ({ title: `${c.icon} ${c.label}`, rows: [{ label: "No mês", value: fmt(byCat[c.key]) }, { label: "Participação", value: `${((byCat[c.key] / catTotal) * 100).toFixed(1)}%` }] }));
        seg.addEventListener("click", () => setCat(c.key));
        return seg;
      })
    );
    $("#compo").hidden = catTotal === 0;
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
              { label: "No mês", value: fmt(byCat[c.key]) },
              { label: "Lançamentos", value: String(countCat[c.key]) },
              ...(compare ? [{ label: `Em ${prevName}`, value: fmt(byCatPrev[c.key] || 0) }] : []),
            ],
          }),
        };
      }),
      { onClick: setCat }
    );
    if (!ranked.length) $("#chart-categories").replaceChildren(h("p", { class: "muted", text: "Nenhum gasto neste mês." }));
    $("#cat-sub").textContent = compare ? `Variação vs ${prevName} · toque para filtrar` : "Por categoria · toque para filtrar";
  }

  function renderMerchants(txs) {
    const cmap = catMap();
    const merchants = {};
    for (const t of txs) {
      const name = t.merchant || t.description;
      const m = (merchants[name.toLowerCase()] ||= { name, total: 0, count: 0, cats: {} });
      m.total += t.amount_cents;
      m.count++;
      m.cats[t.category] = (m.cats[t.category] || 0) + t.amount_cents;
    }
    const top = Object.values(merchants).filter((m) => m.total > 0).sort((a, b) => b.total - a.total).slice(0, 10);
    window.Charts.hbars(
      $("#chart-merchants"),
      top.map((m) => {
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
    if (!top.length) $("#chart-merchants").replaceChildren(h("p", { class: "muted", text: "Nenhum gasto neste mês." }));
    $("#merchants-sub").textContent = state.focus ? `Estabelecimentos do mês em ${focusLabel(state.focus)}` : "Estabelecimentos do mês, na cor da categoria";
  }

  // Spending per month and kind, with each month's income as a tick.
  function renderMonthly(txs) {
    // Up to 12 months, from the first one with data (at least 6 bars), around the chosen month.
    const range = monthRange();
    let end = range[range.length - 1] < state.month ? state.month : range[range.length - 1];
    let start = [Logic.addMonths(end, -11), range[0]].sort().pop();
    if (state.month < start) start = state.month;
    if (Logic.monthDiff(start, end) < 5) start = Logic.addMonths(end, -5);
    if (Logic.monthDiff(start, end) > 11) end = Logic.addMonths(start, 11);
    const keys = [];
    for (let m = start; m <= end; m = Logic.addMonths(m, 1)) keys.push(m);
    const byMonth = Object.fromEntries(keys.map((k) => [k, {}]));
    for (const t of txs) {
      const vals = byMonth[monthOf(t)];
      if (vals) {
        const kind = Logic.kindOf(t);
        vals[kind] = (vals[kind] || 0) + t.amount_cents;
      }
    }
    const incomeOf = (m) => state.incomes.filter((i) => i.start_month <= m && (!i.end_month || i.end_month >= m)).reduce((s, i) => s + i.amount_cents, 0);
    const kinds = Object.entries(KINDS).map(([key, K]) => ({ key, label: K.short, icon: K.icon, color: K.color }));
    const months = keys.map((k, i) => {
      const [y, m] = k.split("-").map(Number);
      const income = state.focus || state.cat ? 0 : incomeOf(k);
      const total = Object.values(byMonth[k]).reduce((a, b) => a + b, 0);
      return {
        key: k,
        label: cap(monthLabel(k)),
        short: MONTHS_SHORT[m - 1],
        year: String(y),
        showYear: i === 0 || m === 1,
        values: byMonth[k],
        total,
        limit: income || null,
        extra: income ? [{ label: "Renda", value: fmt(income) }, { label: "Sobra", value: fmt(income - total) }] : [],
        active: k === state.month,
      };
    });
    window.Charts.stackedColumns($("#chart-monthly"), { months, cats: kinds, onClick: chooseMonth });
    const shown = kinds.filter((c) => months.some((m) => m.values[c.key]));
    const legend = shown.map((c) => h("span", {}, h("i", { style: `background:${c.color}` }), c.label));
    if (months.some((m) => m.limit)) legend.push(h("span", {}, h("i", { class: "tick" }), "renda"));
    $("#legend-monthly").replaceChildren(...legend);
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
    // Grouped by statement month, like the dashboard: a month's total matches its bills.
    const monthSel = $("#tx-month");
    const prevMonth = monthSel.value;
    const months = [...new Set(state.txs.map(monthOf))].sort().reverse();
    monthSel.replaceChildren(h("option", { value: "", text: "Todos os meses" }), ...months.map((m) => h("option", { value: m, text: cap(monthLabel(m)) })));
    monthSel.value = months.includes(prevMonth) ? prevMonth : "";
    const srcSel = $("#tx-source");
    const prevSource = srcSel.value;
    const accounts = new Map();
    for (const t of state.txs) {
      const kind = Logic.kindOf(t);
      const key = kind === "fixo" ? "fixo|" : `${kind}|${t.source}`;
      if (!accounts.has(key)) accounts.set(key, kind === "fixo" ? `${KINDS.fixo.icon} Gastos fixos` : `${KINDS[kind].icon} ${Logic.accountName(t.source) || "Sem cartão"} · ${KINDS[kind].short.toLowerCase()}`);
    }
    const sorted = [...accounts.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    srcSel.replaceChildren(h("option", { value: "", text: "Todos os cartões e contas" }), ...sorted.map(([k, label]) => h("option", { value: k, text: label })));
    srcSel.value = accounts.has(prevSource) ? prevSource : "";

    // Accent-insensitive text search; a value ("45,90") also finds entries of that amount.
    const raw = $("#tx-search").value.trim();
    const q = fold(raw);
    const qAmount = Math.abs(parseAmount(raw));
    const cat = catSel.value;
    const month = monthSel.value;
    const source = srcSel.value;
    const accountOf = (t) => (Logic.kindOf(t) === "fixo" ? "fixo|" : `${Logic.kindOf(t)}|${t.source}`);
    const list = state.txs.filter(
      (t) =>
        (!cat || t.category === cat) &&
        (!month || monthOf(t) === month) &&
        (!source || accountOf(t) === source) &&
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
    for (const t of list) (groups[monthOf(t)] ||= []).push(t);
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
          if (changed) {
            loadBank();
            safely(loadMeta)(); // a sync may have learned the cards' closing and due days
          }
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

  async function loadPlanData() {
    [state.fixed, state.incomes] = await Promise.all([api("/api/fixed"), api("/api/incomes")]);
  }

  async function loadPlan() {
    await loadPlanData();
    if (state.view === "plan") renderPlan();
  }

  function renderPlan() {
    renderPlanSummary();
    renderIncomes();
    renderFixed();
  }

  // This month's plan: income minus fixed expenses = what is left for cards and debit.
  function renderPlanSummary() {
    const m = monthKey(today());
    const active = (x) => x.start_month <= m && (!x.end_month || x.end_month >= m);
    const income = state.incomes.filter(active).reduce((a, i) => a + i.amount_cents, 0);
    const fixed = state.fixed.filter(active).reduce((a, f) => a + f.amount_cents, 0);
    const free = income - fixed;
    $("#plan-summary").replaceChildren(
      h("div", { class: "plan-eq" },
        h("div", {}, h("span", { text: `Renda de ${MONTHS[today().getMonth()]}` }), h("b", { class: "num", text: fmt(income) })),
        h("i", { text: "−" }),
        h("div", {}, h("span", { text: "Gastos fixos" }), h("b", { class: "num", text: fmt(fixed) })),
        h("i", { text: "=" }),
        h("div", { class: free >= 0 ? "good" : "bad" }, h("span", { text: "Para cartões, débito e o resto" }), h("b", { class: "num", text: fmt(free) }))
      ),
      h("p", { class: "muted", text: "No painel, o disponível do mês desconta também as faturas que vencem no mês e o débito." })
    );
  }

  const shortYm = (m) => `${MONTHS_SHORT[+m.slice(5, 7) - 1]}/${m.slice(0, 4)}`;

  function renderIncomes() {
    const current = monthKey(today());
    if (!state.editingIncome && !$("#in-start").value) resetIncomeForm();
    $("#income-list").replaceChildren(
      ...(state.incomes.length
        ? state.incomes.map((i) => {
            const once = i.end_month && i.end_month === i.start_month;
            const ended = i.end_month && i.end_month < current;
            const meta = once ? [`só em ${shortYm(i.start_month)}`] : ["todo mês", `desde ${shortYm(i.start_month)}`, i.end_month && `até ${shortYm(i.end_month)}`];
            if (ended) meta.push("encerrada");
            return h(
              "div",
              { class: "history-row fixed-row", style: ended ? "opacity:.6" : "" },
              h("span", { class: "cat-bubble", style: "--c:var(--good-text)", text: once ? "🎁" : "💰" }),
              h("div", { style: "min-width:0" }, h("div", { class: "title", text: i.description }), h("div", { class: "meta", text: meta.filter(Boolean).join(" · ") })),
              h("b", { class: "num", text: fmt(i.amount_cents) }),
              h(
                "div",
                { class: "fixed-actions" },
                h("button", { class: "btn btn-sm btn-ghost", type: "button", text: "Editar", onclick: () => editIncome(i) }),
                h("button", { class: "btn btn-sm btn-ghost btn-danger", type: "button", text: "Excluir", onclick: safely(() => deleteIncome(i)) })
              )
            );
          })
        : [h("p", { class: "muted", text: "Nenhuma renda ainda. Cadastre os salários abaixo para o painel mostrar quanto sobra no mês." })])
    );
  }

  function syncIncomeKind() {
    const once = $("#in-kind").value === "once";
    $("#in-end-wrap").hidden = once;
    $("#in-start-label").textContent = once ? "Mês" : "A partir de";
  }

  function resetIncomeForm() {
    state.editingIncome = null;
    $("#income-form").reset();
    $("#in-start").value = monthKey(today());
    $("#income-form-title").textContent = "Nova renda";
    $("#income-cancel").hidden = true;
    $("#income-error").hidden = true;
    syncIncomeKind();
  }

  function editIncome(i) {
    state.editingIncome = i;
    $("#in-desc").value = i.description;
    $("#in-amount").value = amountInput(i.amount_cents);
    $("#in-kind").value = i.end_month && i.end_month === i.start_month ? "once" : "monthly";
    $("#in-start").value = i.start_month;
    $("#in-end").value = i.end_month || "";
    $("#income-form-title").textContent = `Editar: ${i.description}`;
    $("#income-cancel").hidden = false;
    $("#income-error").hidden = true;
    syncIncomeKind();
    $("#in-desc").scrollIntoView({ behavior: "smooth", block: "center" });
    $("#in-desc").focus({ preventScroll: true });
  }

  async function saveIncome(e) {
    e.preventDefault();
    const errEl = $("#income-error");
    errEl.hidden = true;
    const cents = parseAmount($("#in-amount").value);
    if (!cents || isNaN(cents) || cents < 0) {
      errEl.textContent = "Informe um valor válido (ex.: 8.000,00).";
      errEl.hidden = false;
      return;
    }
    const once = $("#in-kind").value === "once";
    const payload = {
      description: $("#in-desc").value.trim(),
      amount_cents: cents,
      start_month: $("#in-start").value,
      end_month: once ? $("#in-start").value : $("#in-end").value || null,
    };
    const editing = state.editingIncome;
    const btn = $("#income-save");
    btn.disabled = true;
    try {
      if (editing) await api(`/api/incomes/${editing.id}`, jsonBody(payload, "PUT"));
      else await api("/api/incomes", jsonBody(payload));
      toast(editing ? "Renda atualizada" : "Renda cadastrada 💰");
      resetIncomeForm();
      await loadPlan();
    } catch (ex) {
      errEl.textContent = validationText(ex.body?.detail) || ex.message;
      errEl.hidden = false;
    } finally {
      btn.disabled = false;
    }
  }

  async function deleteIncome(i) {
    if (!confirm(`Excluir a renda “${i.description}”?`)) return;
    await api(`/api/incomes/${i.id}`, { method: "DELETE" });
    if (state.editingIncome?.id === i.id) resetIncomeForm();
    toast("Renda excluída");
    await loadPlan();
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
    const short = shortYm;
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
        : [h("p", { class: "muted", text: "Nenhum gasto fixo ainda. Cadastre aluguel, condomínio, internet, plano de saúde… abaixo." })])
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
      await Promise.all([loadPlan(), loadTxs()]);
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
    await Promise.all([loadPlan(), loadTxs()]);
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
    $("#bank-check-btn").hidden = !b.configured;
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

  // Each card bill as the bank reports it, next to the sum of what was imported.
  async function checkBank() {
    const btn = $("#bank-check-btn");
    const el = $("#bank-check");
    btn.disabled = true;
    el.replaceChildren(h("p", { class: "muted", text: "Consultando os bancos…" }));
    try {
      const { cards } = await api("/api/bank/check");
      const date = (d) => (d ? parseDate(d).toLocaleDateString("pt-BR") : "?");
      el.replaceChildren(
        ...(cards.length ? cards : [null]).map((card) => {
          if (!card) return h("p", { class: "muted", text: "Nenhum cartão de crédito nessas conexões." });
          const rows = card.months.map((m) => {
            const diff = m.bank_cents == null ? null : m.app_cents - m.bank_cents;
            const ok = diff != null && Math.abs(diff) <= 100;
            return h(
              "tr",
              {},
              h("td", { text: `${cap(monthLabel(m.month))}${m.open ? " (aberta)" : ""}` }),
              h("td", { class: "num", style: "text-align:right", text: m.bank_cents == null ? "—" : fmt(m.bank_cents) }),
              h("td", { class: "num", style: "text-align:right", text: `${fmt(m.app_cents)} (${m.count})` }),
              h("td", {
                class: diff == null ? "muted" : ok ? "match-ok" : "match-bad",
                style: "text-align:right",
                text: diff == null ? (m.open ? "fatura ainda aberta" : "o banco não informou") : ok ? "✓ bate" : `${diff > 0 ? "+" : "−"}${fmt(Math.abs(diff))}`,
              }),
              h("td", { class: "muted", style: "font-size:12px", text: m.first ? `compras de ${date(m.first)} a ${date(m.last)}` : "" })
            );
          });
          const others = Object.entries(card.other_months || {}).sort().reverse().slice(0, 4);
          const cycle = [
            `fecha dia ${card.closing_day ?? "?"}, vence dia ${card.due_day ?? "?"}`,
            card.balance_cents != null && `saldo no banco ${fmt(card.balance_cents)}`,
            card.balance_close_date && `fechamento atual ${date(card.balance_close_date)}`,
            card.balance_due_date && `vencimento atual ${date(card.balance_due_date)}`,
          ].filter(Boolean);
          return h(
            "div",
            { style: "margin-top:16px" },
            h("b", { text: card.source }),
            h("div", { class: "muted", style: "font-size:12px", text: cycle.join(" · ") }),
            h(
              "div",
              { class: "table-scroll" },
              h(
                "table",
                { class: "review-table" },
                h("thead", {}, h("tr", {}, h("th", { text: "Fatura (vencimento)" }), h("th", { text: "Banco", style: "text-align:right" }), h("th", { text: "No app", style: "text-align:right" }), h("th", { text: "Diferença", style: "text-align:right" }), h("th", {}))),
                h("tbody", {}, rows)
              )
            ),
            others.length ? h("div", { class: "muted", style: "font-size:12px", text: `Outros meses no app: ${others.map(([m, v]) => `${monthLabel(m)} ${fmt(v)}`).join(" · ")}` }) : null
          );
        })
      );
    } catch (ex) {
      el.replaceChildren(h("div", { class: "notice error", text: ex.message }));
    } finally {
      btn.disabled = false;
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

    const stepMonth = (n) => {
      const months = monthRange();
      const i = months.indexOf(state.month) + n;
      if (i >= 0 && i < months.length) chooseMonth(months[i]);
    };
    $("#month-prev").addEventListener("click", () => stepMonth(-1));
    $("#month-next").addEventListener("click", () => stepMonth(1));

    $("#tx-search").addEventListener("input", refilterTransactions);
    $("#tx-cat").addEventListener("change", refilterTransactions);
    $("#tx-month").addEventListener("change", refilterTransactions);
    $("#tx-source").addEventListener("change", refilterTransactions);

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
    $("#bank-check-btn").addEventListener("click", checkBank);
    $("#fixed-form").addEventListener("submit", saveFixed);
    $("#fixed-cancel").addEventListener("click", resetFixedForm);
    $("#income-form").addEventListener("submit", saveIncome);
    $("#income-cancel").addEventListener("click", resetIncomeForm);
    $("#in-kind").addEventListener("change", syncIncomeKind);

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
    bind();
    await Promise.all([loadMeta(), loadTxs(), loadImports(), loadPlanData()]);
    if (state.imports.some((i) => i.status === "processing")) startPolling();
    const v = location.hash.slice(1);
    setView(VIEWS.includes(v) ? v : "dashboard");
  }

  boot().catch((e) => {
    document.querySelector("main").prepend(h("div", { class: "notice error", text: `Não consegui carregar os dados: ${e.message}` }));
  });
})();
