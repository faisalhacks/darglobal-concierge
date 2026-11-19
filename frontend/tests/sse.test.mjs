// node --test tests/  (Node >= 22.6 strips TS types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createSSEParser } from "../lib/sse.ts";
import { handler, mockMeta } from "../mock/server.mjs";

test("parses frames split across chunks, CRLF and multi-line data", () => {
  const got = [];
  const p = createSSEParser((f) => got.push(f));
  p.push('event: meta\r\ndata: {"lang":"en"}\r\n\r\nevent: tok');
  p.push('en\ndata: {"t":"Hel');
  p.push('lo"}\n\n: comment\n\nevent: done\ndata: {}\n');
  p.end();
  assert.deepEqual(got.map((f) => f.event), ["meta", "token", "done"]);
  assert.equal(JSON.parse(got[1].data).t, "Hello");
});

test("default event name is message; multi data lines joined", () => {
  const got = [];
  const p = createSSEParser((f) => got.push(f));
  p.push("data: a\ndata: b\n\n");
  assert.deepEqual(got, [{ event: "message", data: "a\nb" }]);
});

// ---- Contract C2: the mock must speak the same shapes the backend contract tests assert. ----

test("C2 /api/meta: coverage, llm, starter_chips, llm_available", () => {
  const m = mockMeta();
  assert.equal(typeof m.coverage.DarGlobal.projects, "number");
  assert.equal(typeof m.coverage.DarGlobal.detail_pages, "number");
  assert.equal(m.coverage.DarGlobal.prices_published, false);
  assert.equal(typeof m.coverage.Wasalt.projects, "number");
  assert.equal(typeof m.coverage.Wasalt.listings, "number");
  assert.ok(["live", "mock", "off"].includes(m.llm.mode));
  assert.ok(["ok", "quota", "cooling", "off", "maintenance"].includes(m.llm.state));
  assert.equal(typeof m.llm.budget.used, "number");
  assert.equal(typeof m.llm.budget.cap, "number");
  for (const p of m.llm.pool) assert.ok(["healthy", "cooling", "removed"].includes(p.state));
  assert.equal(m.llm_available, m.llm.state === "ok");
  for (const l of ["en", "ar"]) {
    assert.equal(m.starter_chips[l].length, 5);
    for (const c of m.starter_chips[l]) assert.equal(typeof c, "string");
  }
});

async function withServer(fn) {
  const srv = createServer(handler());
  await new Promise((r) => srv.listen(0, r));
  const base = `http://127.0.0.1:${srv.address().port}`;
  try { return await fn(base); } finally { srv.close(); }
}

async function stream(base, message) {
  const res = await fetch(`${base}/api/chat/stream`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: "t", message, history: [], lang: "auto" }),
  });
  const frames = [];
  const p = createSSEParser((f) => frames.push({ event: f.event, data: JSON.parse(f.data) }));
  p.push(await res.text());
  p.end();
  return frames;
}

const ORDER = ["meta", "token", "cards", "compare", "calc", "sources", "chips", "trace", "done"];

test("C2 SSE: event order unchanged, project cards carry detail/site/price_label/country, trace adds keys", async () => {
  await withServer(async (base) => {
    const frames = await stream(base, "What DarGlobal projects are in Oman?");
    const seq = frames.map((f) => f.event).filter((e, i, a) => e !== "token" || a[i - 1] !== "token");
    const idx = seq.map((e) => ORDER.indexOf(e));
    assert.ok(idx.every((v) => v >= 0), `unknown event in ${seq}`);
    assert.deepEqual([...idx].sort((a, b) => a - b), idx, `out of order: ${seq}`);
    const cards = frames.find((f) => f.event === "cards").data;
    assert.ok(cards.projects.length > 0);
    for (const p of cards.projects) {
      assert.ok(["page", "index"].includes(p.detail));
      assert.equal(typeof p.site, "string");
      assert.equal(typeof p.country, "string");
      assert.equal(p.price_from, null);
      assert.equal(p.price_label, "Price on request");
    }
    const tr = frames.find((f) => f.event === "trace").data;
    for (const k of ["model", "fallback_hops", "cache_hit", "degraded_reason"]) assert.ok(k in tr, `trace.${k}`);
  });
});

test("C2 /api/projects?site=DarGlobal and /readyz keys", async () => {
  await withServer(async (base) => {
    const rows = await (await fetch(`${base}/api/projects?site=DarGlobal&lang=ar`)).json();
    assert.ok(rows.every((r) => r.site === "DarGlobal" && r.price_label === "السعر عند الطلب"));
    const ready = await (await fetch(`${base}/readyz`)).json();
    assert.ok(["ok", "stale", "bm25_only"].includes(ready.index));
    assert.equal(typeof ready.llm, "string");
    assert.equal(typeof ready.xff_hops_seen, "number");
  });
});
