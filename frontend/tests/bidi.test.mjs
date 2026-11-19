// node --test tests/  (Node >= 22.6 strips TS types natively)
// UI spec build item 22: Latin runs, amounts and formulas isolated inside Arabic text.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { splitBidi, isolate, formula, textLang, stripIsolates } from "../lib/bidi.ts";

const html = (node) => renderToStaticMarkup(createElement("p", null, node));
const AR = /[؀-ۿ]/;
const LAT = /[A-Za-z]/;

/** The DOM check of item 22, on static markup: no text outside <bdi> mixes Arabic and Latin letters. */
function mixedOutside(markup) {
  const outside = markup.replace(/<bdi[^>]*>[\s\S]*?<\/bdi>/g, " ").replace(/<[^>]+>/g, " ");
  return AR.test(outside) && LAT.test(outside);
}

test("Latin project names in Arabic prose are isolated, punctuation stays outside", () => {
  const s = "مشروع Trump Tower Jeddah في جدة، ومشروع Neptune.";
  const runs = splitBidi(s, "ar");
  const latin = runs.filter((r) => r.kind === "latin").map((r) => r.text);
  assert.deepEqual(latin, ["Trump Tower Jeddah", "Neptune"]);
  assert.equal(runs.map((r) => r.text).join(""), s);
  const m = html(isolate(s, "ar"));
  assert.ok(!mixedOutside(m), m);
  assert.ok(m.includes('<bdi lang="en">Neptune</bdi>.'), m);
});

test("amount with unit is one isolate", () => {
  const runs = splitBidi("السعر 2,000,000 ر.س للوحدة، أو SAR 1,500,000.", "ar");
  assert.deepEqual(runs.filter((r) => r.kind === "amount").map((r) => r.text), ["2,000,000 ر.س", "SAR 1,500,000"]);
});

test("formula is an LTR isolate and keeps its order", () => {
  const s = "الدفعة الأولى: 2,000,000 × 20% = 400,000 ر.س.";
  const runs = splitBidi(s, "ar");
  const f = runs.find((r) => r.kind === "formula");
  assert.equal(f.text, "2,000,000 × 20% = 400,000 ر.س");
  assert.ok(html(isolate(s, "ar")).includes('<bdi dir="ltr">2,000,000 × 20% = 400,000 ر.س</bdi>.'));
  assert.equal(html(formula("2,000,000 x 20% = 400,000")), '<p><bdi dir="ltr" class="formula">2,000,000 x 20% = 400,000</bdi></p>');
});

test("domains, numbered names and mixed lines", () => {
  for (const s of [
    "الإجابات من darglobal.co.uk و wasalt.sa فقط.",
    "مشروع 7&8 Albert Hall Mansions في لندن.",
    "المشروع: Shams Al Riyadh. الموقع: Wasalt.",
    "According to the page: مشروع فلل إتوال.",
  ]) {
    const m = html(isolate(s, "ar"));
    assert.ok(!mixedOutside(m), m);
    assert.ok(!/<\/bdi>[^<]*^[.،]/.test(m));
  }
});

test("no isolate run starts with sentence punctuation", () => {
  const runs = splitBidi("زر Wasalt، ثم DarGlobal. ثم Interiors by Pagani؟", "ar");
  for (const r of runs.filter((x) => x.kind !== "text")) assert.ok(!/^[.,،؛:!?؟]|[.,،؛:!?؟]$/.test(r.text), r.text);
});

test("English context isolates Arabic runs", () => {
  const s = "Project: مشروع فلل إتوال. Location: Riyadh.";
  const runs = splitBidi(s, "en");
  assert.deepEqual(runs.filter((r) => r.kind === "arabic").map((r) => r.text), ["مشروع فلل إتوال"]);
  assert.ok(!mixedOutside(html(isolate(s, "en"))));
});

test("FSI/PDI marks from i18n become isolates without the marks", () => {
  const s = "المشروع المطابق: ⁨Trump Tower Jeddah⁩";
  const m = html(isolate(s, "ar"));
  assert.ok(!m.includes("⁨") && !m.includes("⁩"), m);
  assert.ok(m.includes("<bdi"));
  assert.equal(stripIsolates(s), "المشروع المطابق: Trump Tower Jeddah");
});

test("pure text comes back as the same string", () => {
  assert.equal(isolate("مرحباً بك", "ar"), "مرحباً بك");
  assert.equal(isolate("Hello there", "en"), "Hello there");
  assert.equal(isolate("في 2026", "ar"), "في 2026");
  assert.equal(textLang("برج ترامب"), "ar");
  assert.equal(textLang("Neptune"), "en");
});
