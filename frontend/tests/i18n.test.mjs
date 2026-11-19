// node --test tests/  (Node >= 22.6 strips TS types natively)
// UI spec build item 21: EN/AR key parity and banned microcopy.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRINGS, DEFAULT_CHIPS, arCount } from "../lib/i18n.ts";

const { en, ar } = STRINGS;

/** Every string an entry can produce: plain strings, record values, and function results for sample args. */
function render(v) {
  if (typeof v === "string") return [v];
  if (typeof v === "function") {
    const out = [];
    for (const n of [0, 0.04, 0.4, 1, 2, 3, 7, 10, 11, 45, 90, 100, 101, 103, 111, 600]) {
      const args = Array.from({ length: v.length }, () => n);
      try { out.push(String(v(...args))); } catch { /* string-only signature */ }
    }
    try { out.push(String(v(...Array.from({ length: v.length }, () => "Trump Tower Jeddah")))); } catch { /* number-only signature */ }
    return out;
  }
  if (v && typeof v === "object") return Object.values(v).flatMap(render);
  return [];
}

test("EN and AR have identical key sets", () => {
  const ek = Object.keys(en).sort();
  const ak = Object.keys(ar).sort();
  assert.deepEqual(ek.filter((k) => !ak.includes(k)), [], "missing in AR");
  assert.deepEqual(ak.filter((k) => !ek.includes(k)), [], "missing in EN");
  for (const k of ek) {
    assert.equal(typeof ar[k], typeof en[k], `type of ${k}`);
    if (typeof en[k] === "function") assert.equal(ar[k].length, en[k].length, `arity of ${k}`);
  }
});

test("new control keys exist with both labels", () => {
  const keys = [
    "appearance", "themeSystem", "themeLight", "themeDark", "textSize", "textSizeDefault", "textSizeLarge",
    "menuOpen", "close", "railCollapse", "railExpand", "railResize", "railResizeHint", "aboutSources", "reviewersLink",
    "welcomeHeadline", "welcomeScope", "legalLine", "stopLabel", "rateLimitedNote",
    "copyAnswer", "regenerate", "helpful", "notHelpful", "notAnswered", "stoppedNote", "noResult",
    "showAll", "alsoListed", "areaAsListed", "carouselNext", "openOn", "originalText",
    "handoffTitle", "handoffContext", "handoffDarglobal", "handoffWasalt", "handoffPrivacy",
    "spotlightScope", "spotlightLead", "traceStepMatched", "traceStepRead", "traceStepCode", "traceTime",
  ];
  for (const k of keys) {
    for (const [lang, d] of [["en", en], ["ar", ar]]) {
      assert.ok(k in d, `${lang}.${k} missing`);
      for (const s of render(d[k])) assert.ok(s.trim().length > 0, `${lang}.${k} is empty`);
    }
  }
  assert.equal(ar.themeSystem, "تلقائي");
  assert.equal(ar.themeLight, "فاتح");
  assert.equal(ar.themeDark, "داكن");
});

const allAr = Object.values(ar).flatMap(render).concat(DEFAULT_CHIPS.ar);
const allEn = Object.values(en).flatMap(render).concat(DEFAULT_CHIPS.en);

test("banned strings are gone", () => {
  const banned = ["نموذج أولي من مرشّح", "بلا مصادر، 0.0 ث", "According to the published information", "وفقاً للمعلومات المنشورة", "كيف وجدت هذه الإجابة"];
  for (const s of [...allAr, ...allEn]) for (const b of banned) assert.ok(!s.includes(b), `"${b}" in "${s}"`);
});

test("no Arabic string abbreviates seconds as ث, and digits are Western", () => {
  for (const s of allAr) {
    assert.ok(!/(^|[\s\d])ث($|[\s.،])/.test(s), `abbreviated seconds in "${s}"`);
    assert.ok(!/[٠-٩]/.test(s), `Arabic-Indic digit in "${s}"`);
  }
});

test("the brand is joined with a no-break space and never split", () => {
  for (const s of allAr) assert.ok(!s.includes("دار جلوبال"), `breakable brand in "${s}"`);
  assert.equal(ar.brandSites, "دار جلوبال · وصلت");
});

test("no attached waw before a Latin run", () => {
  for (const s of allAr) assert.ok(!/و⁨?[A-Za-z]/.test(s), `attached و before Latin in "${s}"`);
});

test("spec copy: prototype line, trace title, rate limit, latency", () => {
  assert.equal(ar.brandSub, "نموذج تجريبي أعدّه متقدّم للوظيفة، وليس قناة رسمية");
  assert.equal(ar.howFound, "كيف توصّلت إلى هذه الإجابة؟");
  assert.equal(ar.rateLimited(5), "تمهّل قليلاً، جرّب بعد 5 ثوانٍ.");
  assert.equal(ar.rateLimited(2), "تمهّل قليلاً، جرّب بعد ثانيتين.");
  assert.equal(ar.rateLimited(30), "تمهّل قليلاً، جرّب بعد 30 ثانية.");
  assert.equal(en.traceSummary(0, 0.04), "no sources, <0.1 s");
  assert.equal(en.traceSummary(3, 0.4), "3 sources, 0.4 s");
  assert.equal(ar.traceSummary(0, 0), "دون مصادر، أقل من 0.1 ثانية");
  assert.equal(ar.traceSummary(2, 0.4), "مصدران، 0.4 ثانية");
});

test("Arabic number agreement", () => {
  const f = { one: "غرفة نوم واحدة", two: "غرفتا نوم", few: "غرف نوم", many: "غرفة نوم" };
  assert.equal(arCount(1, f), "غرفة نوم واحدة");
  assert.equal(arCount(2, f), "غرفتا نوم");
  assert.equal(arCount(3, f), "3 غرف نوم");
  assert.equal(ar.beds(2), "غرفتا نوم");
  assert.equal(ar.listingSources(11), "11 عرضاً على وصلت");
  assert.equal(ar.listingSources(100), "100 عرض على وصلت");
  assert.equal(ar.listingSources(105), "105 عروض على وصلت");
});
