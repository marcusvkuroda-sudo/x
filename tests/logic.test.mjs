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
