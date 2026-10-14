/* Hand-rolled SVG/HTML charts for the dashboard. No external dependencies. */
(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const BRL_COMPACT = new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    notation: "compact",
    maximumFractionDigits: 1,
  });

  const fmt = (cents) => BRL.format(cents / 100);
  const fmtCompact = (cents) =>
    Math.abs(cents) < 100000 ? BRL.format(Math.round(cents / 100)).replace(/,00$/, "") : BRL_COMPACT.format(cents / 100);

  function svg(tag, attrs = {}, parent) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "style") el.style.cssText = v;
      else el.setAttribute(k, v);
    }
    if (parent) parent.appendChild(el);
    return el;
  }

  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style") el.style.cssText = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    }
    return el;
  }

  function niceMax(v) {
    if (v <= 0) return 100;
    const exp = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
      if (m * exp >= v) return m * exp;
    }
    return 10 * exp;
  }

  /* ------------------------------------------------------------ tooltip */

  const tooltip = {
    el: null,
    show(anchor, { title, rows = [], total }) {
      const el = (this.el ||= document.getElementById("tooltip"));
      el.replaceChildren();
      if (title) el.appendChild(h("div", { class: "tt-title", text: title }));
      for (const r of rows) {
        el.appendChild(
          h(
            "div",
            { class: "tt-row" },
            h("span", { class: "k" }, r.color ? h("i", { style: `background:${r.color}` }) : null, h("span", { text: r.label })),
            h("span", { class: "v", text: r.value })
          )
        );
      }
      if (total) {
        el.appendChild(
          h("div", { class: "tt-row tt-total" }, h("span", { class: "k", text: total.label }), h("span", { class: "v", text: total.value }))
        );
      }
      el.classList.add("show");
      this.move(anchor);
    },
    move(anchor) {
      const el = this.el;
      if (!el) return;
      let x, y;
      if (anchor && "clientX" in anchor && anchor.clientX) {
        x = anchor.clientX;
        y = anchor.clientY;
      } else {
        const r = (anchor.currentTarget || anchor.target || anchor).getBoundingClientRect();
        x = r.left + r.width / 2;
        y = r.top;
      }
      const w = el.offsetWidth;
      const ht = el.offsetHeight;
      let left = x + 14;
      if (left + w > window.innerWidth - 8) left = x - w - 14;
      left = Math.max(8, left);
      let top = y - ht - 12;
      if (top < 8) top = y + 18;
      el.style.left = left + "px";
      el.style.top = top + "px";
    },
    hide() {
      if (this.el) this.el.classList.remove("show");
    },
  };

  // On touch screens the pointer "leaves" as soon as the finger lifts, so a tapped
  // tooltip stays open until the next tap elsewhere (or a scroll).
  function bindTooltip(target, getContent) {
    target.dataset.tt = "";
    target.addEventListener("pointerenter", (e) => tooltip.show(e, getContent()));
    target.addEventListener("pointermove", (e) => e.pointerType !== "touch" && tooltip.move(e));
    target.addEventListener("pointerleave", (e) => e.pointerType !== "touch" && tooltip.hide());
    target.addEventListener("focus", (e) => tooltip.show(e, getContent()));
    target.addEventListener("blur", () => tooltip.hide());
  }

  document.addEventListener(
    "pointerdown",
    (e) => {
      if (!(e.target instanceof Element) || !e.target.closest("[data-tt]")) tooltip.hide();
    },
    { passive: true }
  );

  /* ------------------------------------------------------------ stacked columns */

  function stackedColumns(container, { months, cats, onClick }) {
    container.replaceChildren();
    const width = Math.max(container.clientWidth, 280);
    const narrow = width < 520;
    const height = Math.max(container.clientHeight, 230);
    const m = { top: 26, right: 4, bottom: 34, left: narrow ? 46 : 58 };
    const plotW = width - m.left - m.right;
    const plotH = height - m.top - m.bottom;
    const n = months.length;
    const maxTotal = Math.max(0, ...months.map((mo) => Math.max(mo.total, mo.limit || 0)));
    const yMax = niceMax(maxTotal);
    const y = (v) => m.top + plotH - (v / yMax) * plotH;

    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, height, role: "img", "aria-label": "Gastos por mês e categoria" });

    // grid + y axis
    const ticks = 4;
    for (let i = 0; i <= ticks; i++) {
      const v = (yMax / ticks) * i;
      const yy = Math.round(y(v)) + 0.5;
      svg("line", { x1: m.left, x2: width - m.right, y1: yy, y2: yy, style: `stroke:var(${i === 0 ? "--axis" : "--grid"});stroke-width:1` }, root);
      const t = svg("text", { x: m.left - 8, y: yy + 4, "text-anchor": "end", "font-size": 11, style: "fill:var(--muted)" }, root);
      t.textContent = fmtCompact(v);
    }

    const slot = plotW / Math.max(n, 1);
    const barW = Math.min(24, Math.max(8, slot * 0.55));
    const labelEvery = slot < 30 ? 2 : 1;

    const maxIdx = months.reduce((best, mo, i) => (mo.total > months[best].total ? i : best), 0);
    const labelled = new Set([maxIdx, n - 1]);

    const bars = svg("g", {}, root);
    months.forEach((mo, i) => {
      const cx = m.left + slot * i + slot / 2;
      const x = cx - barW / 2;
      const g = svg("g", { style: `opacity:${mo.active ? 1 : 0.35};transition:opacity .15s` }, bars);
      let base = y(0);
      const segs = cats.map((c) => ({ c, v: Math.max(0, mo.values[c.key] || 0) })).filter((s) => s.v > 0);
      segs.forEach((s, si) => {
        const hgt = (s.v / yMax) * plotH;
        const gap = si > 0 && hgt > 3 ? 2 : 0;
        const top = base - hgt;
        const bottom = base - gap;
        const isTop = si === segs.length - 1;
        if (bottom - top < 0.5) {
          base = top;
          return;
        }
        if (isTop) {
          const r = Math.min(4, (bottom - top) / 2, barW / 2);
          const d = `M${x},${bottom} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${bottom} Z`;
          svg("path", { d, style: `fill:${s.c.color}` }, g);
        } else {
          svg("rect", { x, y: top, width: barW, height: bottom - top, style: `fill:${s.c.color}` }, g);
        }
        base = top;
      });

      // A reference per month (the income): a short line across the slot, on the same axis.
      if (mo.limit) {
        const ly = Math.round(y(mo.limit)) + 0.5;
        svg("line", { x1: cx - slot * 0.42, x2: cx + slot * 0.42, y1: ly, y2: ly, style: "stroke:var(--ink-2);stroke-width:2;stroke-linecap:round;stroke-dasharray:4 3" }, g);
      }

      if (labelled.has(i) && mo.total > 0) {
        const nearEdge = cx + 32 > width;
        const t = svg("text", { x: nearEdge ? cx + barW / 2 : cx, y: y(mo.total) - 7, "text-anchor": nearEdge ? "end" : "middle", "font-size": 11, "font-weight": 700, style: "fill:var(--ink)" }, root);
        t.textContent = fmtCompact(mo.total);
      }

      if ((n - 1 - i) % labelEvery === 0) {
        const t = svg("text", { x: cx, y: height - m.bottom + 16, "text-anchor": "middle", "font-size": 11, style: `fill:var(${mo.active ? "--ink-2" : "--muted"});font-weight:${mo.active ? 600 : 400}` }, root);
        t.textContent = mo.short;
        if (mo.showYear) {
          const ty = svg("text", { x: cx, y: height - m.bottom + 29, "text-anchor": "middle", "font-size": 10, style: "fill:var(--muted)" }, root);
          ty.textContent = mo.year;
        }
      }

      const hit = svg("rect", { x: m.left + slot * i, y: m.top, width: slot, height: plotH, fill: "transparent", tabindex: 0, style: "cursor:pointer;outline:none", role: "button", "aria-label": `${mo.label}: ${fmt(mo.total)}` }, root);
      bindTooltip(hit, () => ({
        title: mo.label,
        rows: cats
          .filter((c) => mo.values[c.key])
          .sort((a, b) => mo.values[b.key] - mo.values[a.key])
          .map((c) => ({ color: c.color, label: `${c.icon} ${c.label}`, value: fmt(mo.values[c.key]) }))
          .concat(mo.extra || []),
        total: { label: "Total gasto", value: fmt(mo.total) },
      }));
      hit.addEventListener("pointerenter", () => {
        bars.querySelectorAll("g").forEach((el, j) => (el.style.opacity = j === i ? 1 : 0.3));
      });
      hit.addEventListener("pointerleave", () => {
        bars.querySelectorAll("g").forEach((el, j) => (el.style.opacity = months[j].active ? 1 : 0.35));
      });
      if (onClick) {
        hit.addEventListener("click", () => onClick(mo.key));
        hit.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && onClick(mo.key));
      }
    });

    container.appendChild(root);
  }

  function hbars(container, items, { onClick, compact } = {}) {
    container.replaceChildren();
    const max = Math.max(1, ...items.map((i) => i.value));
    for (const it of items) {
      const pctWidth = Math.max(0, (it.value / max) * 100);
      const row = h(
        "button",
        { class: `hbar${compact ? " compact" : ""}${it.dim ? " dim" : ""}`, type: "button" },
        compact ? null : h("div", { class: "cat-bubble", style: `--c:${it.color}`, text: it.icon || "" }),
        h(
          "div",
          { class: "hbar-main" },
          h("div", { class: "hbar-label" }, h("span", { class: "name", text: (compact && it.icon ? it.icon + " " : "") + it.label }), it.pct != null ? h("span", { class: "pct", text: it.pct }) : null),
          h("div", { class: "hbar-track" }, h("div", { class: "hbar-fill", style: `width:${pctWidth}%;background:${it.color}` }))
        ),
        h("div", { class: "hbar-value" }, fmt(it.value), it.sub ? h("small", { class: it.subClass || null, text: it.sub }) : null)
      );
      if (it.tooltip) bindTooltip(row, it.tooltip);
      if (onClick) row.addEventListener("click", () => onClick(it.key));
      else row.style.cursor = "default";
      container.appendChild(row);
    }
  }

  /* ------------------------------------------------------------ calendar heatmap */

  const WEEKDAYS = ["D", "S", "T", "Q", "Q", "S", "S"];
  const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

  function iso(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  window.Charts = { fmt, fmtCompact, h, stackedColumns, hbars, tooltip, bindTooltip, iso };
})();
