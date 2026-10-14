// Front-end logic tests: node --test tests/
import assert from "node:assert/strict";
import { test } from "node:test";

await import("../static/logic.js");
const { parseAmount, activeInstallments, placeKey } = globalThis.Logic;

test("parseAmount understands Brazilian and US formats", () => {
  const cases = [
    ["45,90", 4590],
    ["1.234,56", 123456],
    ["1,234.56", 123456],
    ["1.234", 123400],
    ["12.5", 1250],
    ["R$ 7", 700],
    ["-59,90", -5990],
  ];
  for (const [input, cents] of cases) assert.equal(parseAmount(input), cents, input);
  assert.ok(Number.isNaN(parseAmount("abc")));
  assert.ok(Number.isNaN(parseAmount("")));
});

test("placeKey ignores case, accents, digits and punctuation", () => {
  assert.equal(placeKey("PÃO DE AÇÚCAR 1234"), "pao de acucar");
  assert.equal(placeKey("UBER *TRIP"), placeKey("Uber trip"));
});

const TODAY = new Date(2026, 9, 10); // 10 Oct 2026
const tx = (o) => ({ merchant: "", description: "X", category: "compras", source: "Nubank", import_id: null, ...o });
const summary = (txs) => activeInstallments(txs, TODAY).map((p) => [p.name, p.k, p.n, p.remaining]);

test("a purchase renamed between statements is counted once", () => {
  const txs = [
    tx({ import_id: 1, date: "2026-08-05", merchant: "Samsung", installment: "3/10", amount_cents: 1000 }),
    tx({ import_id: 2, date: "2026-09-05", merchant: "Samsung Eletrônicos", installment: "4/10", amount_cents: 1000 }),
  ];
  assert.deepEqual(summary(txs), [["Samsung Eletrônicos", 4, 10, 6000]]);
});

test("a card renamed between statements is counted once", () => {
  const txs = [
    tx({ import_id: 1, source: "Nubank", date: "2026-08-05", merchant: "Geladeira", installment: "5/10", amount_cents: 300 }),
    tx({ import_id: 2, source: "Nubank Marcus", date: "2026-09-05", merchant: "Geladeira", installment: "6/10", amount_cents: 300 }),
  ];
  assert.deepEqual(summary(txs), [["Geladeira", 6, 10, 1200]]);
});

test("two cards with the same label keep both purchases", () => {
  const txs = [
    tx({ import_id: 1, date: "2026-09-03", merchant: "TV", installment: "2/5", amount_cents: 500 }),
    tx({ import_id: 2, date: "2026-09-10", merchant: "Sofá", installment: "4/8", amount_cents: 900 }),
  ];
  assert.equal(summary(txs).length, 2);
});

test("identical purchases on the same statement stay separate", () => {
  const line = (id, date, k) => tx({ import_id: id, date, merchant: "Ingresso", installment: `${k}/3`, amount_cents: 100 });
  const txs = [line(1, "2026-08-05", 1), line(1, "2026-08-05", 1), line(2, "2026-09-05", 2), line(2, "2026-09-05", 2)];
  assert.deepEqual(summary(txs), [["Ingresso", 2, 3, 100], ["Ingresso", 2, 3, 100]]);
});

test("first installment dated with the purchase date still matches", () => {
  const txs = [
    tx({ import_id: 1, date: "2026-08-28", merchant: "Bike", installment: "1/10", amount_cents: 200 }),
    tx({ import_id: 2, date: "2026-10-03", merchant: "Bike", installment: "2/10", amount_cents: 200 }),
  ];
  assert.deepEqual(summary(txs), [["Bike", 2, 10, 1600]]);
});

test("statements imported out of order keep the latest installment", () => {
  const txs = [
    tx({ import_id: 2, date: "2026-09-05", merchant: "Bike", installment: "4/10", amount_cents: 200 }),
    tx({ import_id: 1, date: "2026-08-05", merchant: "Bike", installment: "3/10", amount_cents: 200 }),
  ];
  assert.deepEqual(summary(txs), [["Bike", 4, 10, 1200]]);
});

test("finished and stale purchases are not pending", () => {
  const txs = [
    tx({ import_id: 1, date: "2026-09-05", merchant: "Fim", installment: "10/10", amount_cents: 200 }),
    tx({ import_id: 3, date: "2025-01-05", merchant: "Velha", installment: "2/10", amount_cents: 200 }),
  ];
  assert.deepEqual(summary(txs), []);
});

test("a bank sync bringing several statements counts each purchase once", () => {
  const line = (bill, k, source = "Santander cartão") =>
    tx({ import_id: 7, source, date: `${bill}-10`, bill_month: bill, merchant: "Magalu", installment: `${k}/10`, amount_cents: 12000 });
  const txs = [line("2026-07", 2), line("2026-08", 3), line("2026-09", 4), line("2026-09", 4, "Inter cartão")];
  // The Inter card has its own purchase with the same value: still two purchases.
  assert.deepEqual(summary(txs), [["Magalu", 4, 10, 72000], ["Magalu", 4, 10, 72000]]);
});

test("statement month beats the date when matching installments", () => {
  // 1st installment dated on the purchase (July), billed in August; 2nd billed in September.
  const txs = [
    tx({ import_id: 1, date: "2026-07-28", bill_month: "2026-08", merchant: "Sofá", installment: "1/6", amount_cents: 500 }),
    tx({ import_id: 2, date: "2026-09-05", bill_month: "2026-09", merchant: "Sofá", installment: "2/6", amount_cents: 500 }),
  ];
  assert.deepEqual(summary(txs), [["Sofá", 2, 6, 2000]]);
});

/* ------------------------------------------------------------ month summary (the couple's October) */
{
  const { monthSummary, billInfo, kindOf, accountName } = globalThis.Logic;
  const TODAY14 = new Date(2026, 9, 14); // 14 Oct 2026
  const cards = { "Santander cartão": { closing_day: 9, due_day: 17 }, "Inter cartão": { closing_day: 11, due_day: 18 } };
  const t = (o) => ({ origin: "import", import_id: 1, merchant: "", description: "X", category: "outros", installment: null, ...o });
  const txs = [
    // Santander: October's bill (closed on 09/10) and November's, open.
    t({ source: "Santander cartão", date: "2026-09-20", bill_month: "2026-10", amount_cents: 300000 }),
    t({ source: "Santander cartão", date: "2026-10-05", bill_month: "2026-10", amount_cents: 74052 }),
    t({ source: "Santander cartão", date: "2026-10-10", bill_month: "2026-11", amount_cents: 7359 }),
    t({ source: "Santander cartão", date: "2026-10-12", bill_month: "2026-11", amount_cents: 33100 }),
    t({ source: "Santander cartão", date: "2026-10-12", bill_month: "2026-11", amount_cents: 4420, installment: "1/6", description: "AMAZON BR" }),
    // Inter: three installments 11/12 in October; only one 12/12 posted in November so far.
    t({ source: "Inter cartão", import_id: 2, date: "2026-09-13", bill_month: "2026-10", amount_cents: 8266, installment: "11/12", description: "ATLASELE" }),
    t({ source: "Inter cartão", import_id: 2, date: "2026-09-27", bill_month: "2026-10", amount_cents: 19991, installment: "11/12", description: "SHOPEE" }),
    t({ source: "Inter cartão", import_id: 2, date: "2026-09-27", bill_month: "2026-10", amount_cents: 3480, installment: "11/12", description: "MERCADO" }),
    t({ source: "Inter cartão", import_id: 3, date: "2026-10-13", bill_month: "2026-11", amount_cents: 8266, installment: "12/12", description: "ATLASELE" }),
    // Debit card and the rent (fixed expense).
    t({ source: "Santander débito", date: "2026-10-02", bill_month: null, amount_cents: 5000 }),
    t({ source: "Santander débito", date: "2026-10-06", bill_month: null, amount_cents: 4000 }),
    t({ source: "Santander débito", date: "2026-10-08", bill_month: null, amount_cents: 4000 }),
    t({ origin: "fixed", source: "", date: "2026-10-05", bill_month: "2026-10", amount_cents: 320000, description: "Aluguel" }),
  ];
  const opts = {
    today: TODAY14,
    cards,
    fixed: [{ description: "Aluguel", amount_cents: 320000, start_month: "2026-07", end_month: null }],
    incomes: [{ description: "Salários", amount_cents: 800000, start_month: "2026-01", end_month: null }],
  };
  const byName = (s) => Object.fromEntries(s.groups.flatMap((g) => g.accounts.map((a) => [`${g.kind}:${a.name}`, a])));

  test("kinds and account names", () => {
    assert.equal(kindOf({ origin: "import", source: "Santander cartão" }), "credito");
    assert.equal(kindOf({ origin: "import", source: "Santander débito" }), "debito");
    assert.equal(kindOf({ origin: "fixed", source: "" }), "fixo");
    assert.equal(kindOf({ origin: "manual", source: "" }), "outros");
    assert.equal(kindOf({ origin: "manual", source: "Inter cartão" }), "credito");
    assert.equal(accountName("Inter cartão"), "Inter");
  });

  test("bill status from the card cycle", () => {
    const s = cards["Santander cartão"];
    assert.deepEqual(billInfo("2026-10", s, "2026-10-14"), { state: "closed", opens: "2026-09-10", closes: "2026-10-09", due: "2026-10-17" });
    assert.equal(billInfo("2026-11", s, "2026-10-14").state, "open");
    assert.equal(billInfo("2026-12", s, "2026-10-14").state, "future");
    // Cards that close at the end of the month, due early the next one.
    assert.deepEqual(billInfo("2026-11", { closing_day: 26, due_day: 5 }, "2026-10-20"), { state: "open", opens: "2026-09-27", closes: "2026-10-26", due: "2026-11-05" });
  });

  test("October: what was spent, the projection and what is left", () => {
    const s = monthSummary(txs, "2026-10", opts);
    const a = byName(s);
    assert.equal(s.when, "current");
    assert.equal(a["credito:Santander"].total, 374052); // = October's bill
    assert.equal(a["credito:Santander"].bill.state, "closed");
    assert.equal(a["credito:Inter"].total, 31737);
    assert.equal(a["debito:Santander"].total, 13000);
    assert.equal(a["debito:Santander"].pace, Math.round((13000 / 14) * 17)); // the rest of the month at the same pace
    assert.equal(a["fixo:Gastos fixos"].total, 320000);
    assert.equal(s.income, 800000);
    assert.equal(s.spent, 374052 + 31737 + 13000 + 320000);
    assert.equal(s.left, 800000 - s.spent);
    assert.equal(s.projected, s.spent + a["debito:Santander"].pace);
  });

  test("November: open bills, installments still to come and planned fixed expenses", () => {
    const s = monthSummary(txs, "2026-11", opts);
    const a = byName(s);
    assert.equal(s.when, "future");
    // Inter: 12/12 posted + the two 12/12 still to come = its next bill, R$ 317,37.
    assert.equal(a["credito:Inter"].total, 8266);
    assert.equal(a["credito:Inter"].projected, 31737);
    // Santander: open since 10/10, closes 09/11; the pace of its purchases (not installments) goes on.
    const sant = a["credito:Santander"];
    assert.equal(sant.bill.state, "open");
    assert.equal(sant.total, 7359 + 33100 + 4420);
    assert.equal(sant.pace, Math.round(((7359 + 33100) / 5) * 26));
    assert.equal(sant.projected, sant.total + sant.pace);
    // The rent comes from its definition (November's entry isn't created yet).
    assert.equal(a["fixo:Gastos fixos"].total, 0);
    assert.equal(a["fixo:Gastos fixos"].projected, 320000);
    assert.equal(s.leftProjected, 800000 - s.projected);
  });
}
