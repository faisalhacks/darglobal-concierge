// node --test tests/  (Node >= 22.6 strips TS types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import { applyFilters, countBy, NO_FILTERS, parseAll, prettify, totalsOf } from "../lib/evalsAll.ts";

const mk = (i, s, ok, extra = {}) => ({ i, s, c: "injection", p: null, l: "en", q: ["hello there"], a: "a reply", ok, f: ok === 0 ? ["no_promise"] : [], src: "built by code", ...extra });
const E = [
  mk("A1", "mock", 1), mk("A2", "mock", 0, { q: ["promise me returns"], f: ["no_promise"] }), mk("A3", "mock", -1),
  mk("P1.1", "personas:before", 1, { p: "investor", c: "yield_bait", src: "live model via NVIDIA" }),
  mk("P1.2", "personas:before", 0, { p: "investor", c: "yield_bait", src: "live model via NVIDIA", f: ["no_advice"] }),
];

test("no filters keeps every entry, failures first", () => {
  const r = applyFilters(E, NO_FILTERS);
  assert.equal(r.length, 5);
  assert.deepEqual(r.slice(0, 2).map((e) => e.ok), [0, 0]);
  assert.equal(r[2].ok, -1);
});

test("source, persona, result and answered-by filters combine", () => {
  assert.equal(applyFilters(E, { ...NO_FILTERS, source: "mock" }).length, 3);
  assert.equal(applyFilters(E, { ...NO_FILTERS, persona: "investor" }).length, 2);
  assert.equal(applyFilters(E, { ...NO_FILTERS, persona: "none" }).length, 3);
  assert.equal(applyFilters(E, { ...NO_FILTERS, persona: "investor", result: "failed" }).length, 1);
  assert.equal(applyFilters(E, { ...NO_FILTERS, answered: "live model via NVIDIA" }).length, 2);
  assert.equal(applyFilters(E, { ...NO_FILTERS, result: "skipped" })[0].i, "A3");
});

test("search looks in questions, ids and failing check names, case-insensitively", () => {
  assert.deepEqual(applyFilters(E, { ...NO_FILTERS, query: "PROMISE ME" }).map((e) => e.i), ["A2"]);
  assert.deepEqual(applyFilters(E, { ...NO_FILTERS, query: "no_advice" }).map((e) => e.i), ["P1.2"]);
  assert.equal(applyFilters(E, { ...NO_FILTERS, query: "zzz-nothing" }).length, 0);
});

test("totals add up and a bad file becomes null", () => {
  const t = totalsOf([{ key: "a", set: "a", name: "a", n: 10, passed: 8, failed: 1, skipped: 1 }, { key: "b", set: "b", name: "b", n: 5, passed: 5, failed: 0, skipped: 0 }]);
  assert.deepEqual(t, { n: 15, passed: 13, failed: 1, skipped: 1 });
  assert.equal(parseAll(null), null);
  assert.equal(parseAll({ entries: "x", sources: [] }), null);
  assert.equal(parseAll({ entries: [{ i: "x", q: [], a: "", ok: 7 }, mk("ok", "s", 1)], sources: [] }).entries.length, 1);
});

test("countBy and prettify", () => {
  assert.deepEqual(countBy(E, (e) => e.c)[0], ["injection", 3]);
  assert.equal(prettify("yield_bait"), "Yield bait");
});
