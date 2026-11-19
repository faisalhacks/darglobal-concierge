// node --test tests/  (Node >= 22.6 strips TS types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import { createSSEParser } from "../lib/sse.ts";

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
