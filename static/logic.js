/* Pure helpers (no DOM), shared by the page and by tests/logic.test.mjs. */
(function (root) {
  // A card with no statement imported for this long no longer shows pending installments.
  const INSTALLMENTS_STALE_DAYS = 62;

  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  const fold = (text) =>
    String(text || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();

  // Same idea as the server's category rules: letters only, so "UBER *TRIP 123" ~ "uber trip".
  const placeKey = (text) => fold(text).replace(/[^a-z]+/g, " ").trim();

  // "45,90", "1.234,56", "1,234.56", "R$ 7" -> cents (NaN when it isn't a number).
  function parseAmount(raw) {
    let s = String(raw ?? "").replace(/[R$\s]/g, "");
    if (!s) return NaN;
    const neg = s.startsWith("-");
    s = s.replace(/^[-+]/, "");
    const comma = s.lastIndexOf(",");
    const dot = s.lastIndexOf(".");
    if (comma >= 0 && dot >= 0) {
      // Both separators: whichever comes last is the decimal one.
      s = comma > dot ? s.replace(/\./g, "").replace(",", ".") : s.replace(/,/g, "");
    } else if (comma >= 0) {
      s = s.replace(",", ".");
    } else if (/^\d{1,3}(\.\d{3})+$/.test(s)) {
      s = s.replace(/\./g, "");
    }
    if (!/^\d*\.?\d*$/.test(s)) return NaN;
    const v = parseFloat(s);
    return isNaN(v) ? NaN : Math.round(v * 100) * (neg ? -1 : 1);
  }

  const amountInput = (cents) => (cents / 100).toFixed(2).replace(".", ",");

  // A running installment shows up again on every statement, and the same purchase may be
  // named differently from one month to the next ("Samsung" / "Samsung Eletrônicos") or come
  // from cards with the same label. Names can't be trusted, so a purchase is identified by
  // its number of installments, the installment value and the month it started
  // (statement month minus installments already paid, with one month of slack because the
  // first installment may carry the purchase date). Lines of one statement are always
  // different purchases, even when identical. A bank sync brings several statements at once,
  // so a statement is an import plus its statement month.
  function activeInstallments(txs, today = new Date()) {
    const cutoff = iso(new Date(today.getTime() - INSTALLMENTS_STALE_DAYS * 864e5));
    const monthIndex = (d) => +d.slice(0, 4) * 12 + +d.slice(5, 7) - 1;
    const cleanName = (t) => (t.merchant || t.description).replace(/\s*(parc(ela)?\.?\s*)?\d{1,3}\s*\/\s*\d{1,3}\s*$/i, "").trim();
    const batches = new Map(); // statement (import + statement month) or manual entry date -> lines
    for (const t of txs) {
      const m = /^(\d+)\/(\d+)$/.exec(t.installment || "");
      if (!m || +m[2] < 2) continue;
      const key = t.import_id ? `i${t.import_id}:${t.bill_month || ""}` : `m${t.date}`;
      if (!batches.has(key)) batches.set(key, []);
      batches.get(key).push({ t, k: +m[1], n: +m[2], start: monthIndex(t.bill_month || t.date) - (+m[1] - 1) });
    }
    const lastDate = (lines) => lines.reduce((a, l) => (l.t.date > a ? l.t.date : a), "");
    const purchases = [];
    for (const lines of [...batches.values()].sort((a, b) => (lastDate(a) < lastDate(b) ? -1 : 1))) {
      const matched = new Set();
      for (const line of lines) {
        const gap = (p) => Math.abs(p.start - line.start);
        const p = purchases
          .filter((p) => !matched.has(p) && p.n === line.n && p.amount === line.t.amount_cents && gap(p) <= 1)
          .sort((a, b) => gap(a) - gap(b) || Math.abs(line.k - a.k) - Math.abs(line.k - b.k))[0];
        const target = p || { n: line.n, amount: line.t.amount_cents, k: 0, last: "" };
        if (!p) purchases.push(target);
        matched.add(target);
        // Statements may be imported out of order: keep the most advanced installment seen.
        if (line.k > target.k)
          Object.assign(target, {
            k: line.k,
            start: line.start,
            name: cleanName(line.t),
            category: line.t.category,
            source: line.t.source || "",
            month: monthOf(line.t), // statement month of the last installment seen
          });
        if (line.t.date > target.last) target.last = line.t.date;
      }
    }
    return purchases
      .filter((p) => p.k < p.n && p.last >= cutoff)
      .map((p) => ({ ...p, remaining: (p.n - p.k) * p.amount }))
      .sort((a, b) => b.remaining - a.remaining);
  }

  /* ---------------------------------------------------------- month summary */

  const pad = (n) => String(n).padStart(2, "0");
  const monthOf = (t) => t.bill_month || t.date.slice(0, 7);
  const addMonths = (month, n) => {
    const i = +month.slice(0, 4) * 12 + +month.slice(5, 7) - 1 + n;
    return `${Math.floor(i / 12)}-${pad((i % 12) + 1)}`;
  };
  const monthDiff = (a, b) => (+b.slice(0, 4) - +a.slice(0, 4)) * 12 + (+b.slice(5, 7) - +a.slice(5, 7));
  const daysIn = (y, m) => new Date(y, m, 0).getDate();
  const dayOf = (month, day) => `${month}-${pad(Math.min(day, daysIn(+month.slice(0, 4), +month.slice(5, 7))))}`;
  const daysBetween = (a, b) => Math.round((Date.UTC(+b.slice(0, 4), +b.slice(5, 7) - 1, +b.slice(8, 10)) - Date.UTC(+a.slice(0, 4), +a.slice(5, 7) - 1, +a.slice(8, 10))) / 864e5);
  const nextDay = (d) => {
    const x = new Date(Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10) + 1));
    return `${x.getUTCFullYear()}-${pad(x.getUTCMonth() + 1)}-${pad(x.getUTCDate())}`;
  };

  // What kind of money an entry is: a card bill, a debit/account purchase, a fixed expense or a
  // manual entry without a card.
  function kindOf(t) {
    if (t.origin === "fixed") return "fixo";
    const s = fold(t.source);
    if (/\b(debito|conta)\b/.test(s)) return "debito";
    if (t.origin === "import" || /cartao|credito/.test(s)) return "credito";
    return "outros";
  }

  // "Santander cartão" -> "Santander"
  const accountName = (source) => String(source || "").replace(/\s*(cart[aã]o|cr[eé]dito|d[eé]bito|conta)\s*$/i, "").trim();

  // A card bill is named by its due month. With the card's closing and due days, tells when it
  // opens and closes and whether it is closed, open (can still grow) or not started yet.
  function billInfo(month, cycle, today) {
    const closingMonth = cycle.closing_day >= cycle.due_day ? addMonths(month, -1) : month;
    const closes = dayOf(closingMonth, cycle.closing_day);
    const opens = nextDay(dayOf(addMonths(closingMonth, -1), cycle.closing_day));
    const due = dayOf(month, cycle.due_day);
    const state = today > closes ? "closed" : today >= opens ? "open" : "future";
    return { state, opens, closes, due };
  }

  // Installments still to come of the purchases in progress: {source: {month: cents}}.
  function upcomingInstallments(txs, today) {
    const out = {};
    for (const p of activeInstallments(txs, today)) {
      for (let i = 1; i <= p.n - p.k; i++) {
        const m = addMonths(p.month, i);
        ((out[p.source] ||= {})[m] ||= 0);
        out[p.source][m] += p.amount;
      }
    }
    return out;
  }

  const activeIn = (item, month) => item.start_month <= month && (!item.end_month || item.end_month >= month);

  /*
   * Everything about one month, by statement month (what leaves the account that month):
   * income, what was spent per card / account, and the projection to the end of the month.
   *   txs      transactions (with bill_month)
   *   opts     { today (Date), cards: {source: {closing_day, due_day}}, fixed: [...], incomes: [...] }
   */
  function monthSummary(txs, month, opts) {
    const today = iso(opts.today || new Date());
    const current = today.slice(0, 7);
    const cards = opts.cards || {};
    const upcoming = upcomingInstallments(txs, opts.today || new Date());
    const inMonth = txs.filter((t) => monthOf(t) === month);
    const accounts = new Map(); // kind|source -> account
    const account = (kind, source) => {
      const key = `${kind}|${source}`;
      if (!accounts.has(key)) accounts.set(key, { kind, source, name: accountName(source), total: 0, count: 0, items: [] });
      return accounts.get(key);
    };
    for (const t of inMonth) {
      const kind = kindOf(t);
      const a = account(kind, kind === "fixo" ? "Gastos fixos" : t.source || "");
      a.total += t.amount_cents;
      a.count++;
      if (kind === "fixo") a.items.push({ name: t.merchant || t.description, amount: t.amount_cents });
    }
    // Fixed expenses of months not reached yet come from their definitions.
    if (month > current) {
      for (const f of (opts.fixed || []).filter((f) => activeIn(f, month))) {
        const a = account("fixo", "Gastos fixos");
        a.projectedExtra = (a.projectedExtra || 0) + f.amount_cents;
        a.items.push({ name: f.description, amount: f.amount_cents, planned: true });
      }
    }
    // Cards with a bill to come this month, even if nothing was posted yet.
    for (const [source, byMonth] of Object.entries(upcoming)) if (byMonth[month]) account("credito", source);

    for (const a of accounts.values()) {
      a.projected = a.total + (a.projectedExtra || 0);
      if (a.kind === "credito") {
        const cycle = cards[a.source];
        a.bill = cycle ? billInfo(month, cycle, today) : null;
        const closed = a.bill ? a.bill.state === "closed" : month < current;
        if (!closed) {
          a.projected += (upcoming[a.source] || {})[month] || 0;
          if (a.bill && a.bill.state === "open") {
            // Keep the pace of the purchases made so far in this bill until it closes.
            const elapsed = daysBetween(a.bill.opens, today) + 1;
            const left = daysBetween(today, a.bill.closes);
            const bought = inMonth
              .filter((t) => t.source === a.source && kindOf(t) === "credito" && !t.installment && t.amount_cents > 0 && t.date >= a.bill.opens)
              .reduce((s, t) => s + t.amount_cents, 0);
            if (elapsed >= 3 && left > 0) a.pace = Math.round((bought / elapsed) * left);
            a.projected += a.pace || 0;
          }
        }
      } else if (a.kind === "debito" && month === current) {
        const day = +today.slice(8, 10);
        const left = daysIn(+month.slice(0, 4), +month.slice(5, 7)) - day;
        if (day >= 3 && left > 0) a.pace = Math.round((a.total / day) * left);
        a.projected += a.pace || 0;
      }
    }

    const KINDS = ["credito", "debito", "fixo", "outros"];
    const groups = KINDS.map((kind) => {
      const list = [...accounts.values()].filter((a) => a.kind === kind).sort((x, y) => y.projected - x.projected);
      return {
        kind,
        accounts: list,
        total: list.reduce((s, a) => s + a.total, 0),
        projected: list.reduce((s, a) => s + a.projected, 0),
      };
    }).filter((g) => g.accounts.length);
    const incomes = (opts.incomes || []).filter((i) => activeIn(i, month));
    const income = incomes.reduce((s, i) => s + i.amount_cents, 0);
    const spent = groups.reduce((s, g) => s + g.total, 0);
    const projected = groups.reduce((s, g) => s + g.projected, 0);
    return {
      month,
      when: month < current ? "past" : month === current ? "current" : "future",
      income,
      incomes,
      groups,
      spent,
      projected,
      left: income - spent,
      leftProjected: income - projected,
    };
  }

  root.Logic = {
    fold,
    placeKey,
    parseAmount,
    amountInput,
    activeInstallments,
    monthOf,
    addMonths,
    monthDiff,
    kindOf,
    accountName,
    billInfo,
    upcomingInstallments,
    monthSummary,
  };
})(typeof window !== "undefined" ? window : globalThis);
