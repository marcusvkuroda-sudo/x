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
  // first installment carries the purchase date). Lines of one statement are always
  // different purchases, even when identical.
  function activeInstallments(txs, today = new Date()) {
    const cutoff = iso(new Date(today.getTime() - INSTALLMENTS_STALE_DAYS * 864e5));
    const monthIndex = (d) => +d.slice(0, 4) * 12 + +d.slice(5, 7) - 1;
    const cleanName = (t) => (t.merchant || t.description).replace(/\s*(parc(ela)?\.?\s*)?\d{1,3}\s*\/\s*\d{1,3}\s*$/i, "").trim();
    const batches = new Map(); // statement (import) or manual entry date -> lines
    for (const t of txs) {
      const m = /^(\d+)\/(\d+)$/.exec(t.installment || "");
      if (!m || +m[2] < 2) continue;
      const key = t.import_id ? `i${t.import_id}` : `m${t.date}`;
      if (!batches.has(key)) batches.set(key, []);
      batches.get(key).push({ t, k: +m[1], n: +m[2], start: monthIndex(t.date) - (+m[1] - 1) });
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
        if (line.k > target.k) Object.assign(target, { k: line.k, start: line.start, name: cleanName(line.t), category: line.t.category });
        if (line.t.date > target.last) target.last = line.t.date;
      }
    }
    return purchases
      .filter((p) => p.k < p.n && p.last >= cutoff)
      .map((p) => ({ ...p, remaining: (p.n - p.k) * p.amount }))
      .sort((a, b) => b.remaining - a.remaining);
  }

  root.Logic = { fold, placeKey, parseAmount, amountInput, activeInstallments };
})(typeof window !== "undefined" ? window : globalThis);
