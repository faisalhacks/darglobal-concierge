// node --test tests/  (Node >= 22.6 strips TS types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseInline, parseMarkdown } from "../lib/md.ts";

const flat = (line) => line.map((s) => (s.strong ? `<b>${s.text}</b>` : s.em ? `<i>${s.text}</i>` : s.text)).join("");

test("bold and emphasis, no literal asterisks", () => {
  assert.equal(flat(parseInline("A **bold** and *soft* word")), "A <b>bold</b> and <i>soft</i> word");
  assert.equal(flat(parseInline("**مرحلة الإدراج** - نص")), "<b>مرحلة الإدراج</b> - نص");
});

test("spaced asterisk stays literal; stray ** is dropped when done", () => {
  assert.equal(flat(parseInline("2 * 3 = 6")), "2 * 3 = 6");
  assert.equal(flat(parseInline("broken **bold")), "broken bold");
});

test("streaming: a half-arrived delimiter never flashes", () => {
  assert.equal(flat(parseInline("Step **List", true)), "Step <b>List</b>");
  assert.equal(flat(parseInline("Step **Listing*", true)), "Step <b>Listing</b>");
  assert.equal(flat(parseInline("Step *", true)), "Step ");
  assert.equal(flat(parseInline("Step **", true)), "Step ");
  for (const chunk of ["1. **Listing & Inspection** - the", "1. **Listing & Insp", "1. **Listing & Inspection*"]) {
    const blocks = parseMarkdown(chunk, true);
    assert.equal(blocks[0].type, "ol");
    assert.ok(!flat(blocks[0].items[0].line).includes("*"), chunk);
  }
});

test("numbered list with bold lead-ins (the auctions answer)", () => {
  const md = "Wasalt auctions work in steps:\n\n1. **Listing & Inspection** - the property is listed.\n2. **Registration** - bidders register [1].\n3. **Bidding** - live.\n\nAsk me for details.";
  const b = parseMarkdown(md);
  assert.deepEqual(b.map((x) => x.type), ["p", "ol", "p"]);
  assert.equal(b[1].items.length, 3);
  assert.equal(flat(b[1].items[0].line), "<b>Listing & Inspection</b> - the property is listed.");
  assert.ok(flat(b[1].items[1].line).includes("[1]"));
  assert.equal(JSON.stringify(b).includes("**"), false);
});

test("bullets, nested bullets, headings and line breaks", () => {
  const b = parseMarkdown("### Options\n- One\n  - sub\n* Two\nline a\nline b");
  assert.equal(b[0].type, "h");
  assert.equal(flat(b[0].line), "Options");
  assert.equal(b[1].type, "ul");
  assert.equal(b[1].items.length, 2);
  assert.equal(flat(b[1].items[0].sub[0]), "sub");
  assert.equal(b[2].type, "p");
  assert.equal(b[2].lines.length, 2);
});

test("no links or HTML from model text", () => {
  const line = parseInline('See [the page](https://evil.example/x) and <img src=x onerror=alert(1)> `code`');
  assert.equal(flat(line), "See the page and <img src=x onerror=alert(1)> code");
  // the HTML stays a text span (React escapes it); no span carries an href
  assert.ok(line.every((s) => Object.keys(s).every((k) => ["text", "strong", "em"].includes(k))));
});

test("bidi isolates (FSI/PDI) around Latin names survive markdown parsing", () => {
  const src = "\u2068Trump Furnished Residences\u2069\u060c \u2068Marriott Residences\u2069 و **\u2068Aida\u2069**";
  const out = flat(parseInline(src));
  assert.ok(out.includes("\u2068Trump Furnished Residences\u2069\u060c \u2068Marriott Residences\u2069"));
  assert.ok(out.includes("<b>\u2068Aida\u2069</b>"));
  const blocks = parseMarkdown("- \u2068Aida\u2069\u060c\n- \u2068Neptune\u2069");
  assert.ok(JSON.stringify(blocks).includes("\u2068Aida\u2069") || JSON.stringify(blocks).includes("\u2068Aida\u2069"));
});
