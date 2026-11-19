// Safe minimal Markdown for assistant prose. Output is plain data rendered as React text nodes, so nothing the model
// writes can become HTML. Supported: **bold**, *emphasis*, "-"/"*"/"•" bullets, "1." / "1)" numbered lists (one nested
// bullet level), "#" headings (shown as a bold line), single line breaks, blank-line paragraphs. Model links never become
// links: "[label](url)" shows its label only, and backticks are dropped. [n] citation markers are left in the text for
// the caller to turn into chips.
// Streaming-safe: with `streaming`, a delimiter at the very end of the text (a "*" or "**" split across chunks) is
// hidden, and an opener still waiting for its closer styles the rest of the text instead of showing as asterisks.

export interface Span { text: string; strong?: boolean; em?: boolean }
export type Line = Span[];
export interface ListItem { line: Line; sub?: Line[] }
export type Block =
  | { type: "p"; lines: Line[] }
  | { type: "h"; line: Line }
  | { type: "ul"; items: ListItem[] }
  | { type: "ol"; start: number; items: ListItem[] };

const BULLET = /^(\s*)[-•*+]\s+(.*)$/;
const ORDERED = /^(\s*)(\d{1,3})[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/;

type Tok = { kind: "text"; v: string } | { kind: "delim"; v: "**" | "*"; open: boolean; close: boolean; pos: number };

function cleanText(s: string): string {
  return s
    .replace(/!?\[([^\]\n]*)\]\((?:[^)\s]*)(?:\s+"[^"]*")?\)/g, "$1") // [label](url) / ![alt](src) -> label
    .replace(/`+/g, ""); // inline code ticks
}

/** Inline emphasis for one line. */
export function parseInline(src: string, streaming = false): Line {
  // Streaming: trailing asterisks may be half a delimiter; hide them (an opener left unpaired styles the rest anyway).
  const s = streaming ? cleanText(src).replace(/\*+$/, "") : cleanText(src);
  const toks: Tok[] = [];
  let buf = "";
  for (let i = 0; i < s.length; ) {
    if (s[i] === "*") {
      const run = s[i + 1] === "*" ? "**" : "*";
      // a run of three or more is ambiguous; treat "***" as "**" followed by "*"
      const prev = i > 0 ? s[i - 1] : " ";
      const next = s[i + run.length] ?? " ";
      const open = !/\s/.test(next);
      const close = !/\s/.test(prev);
      if (open || close) {
        if (buf) { toks.push({ kind: "text", v: buf }); buf = ""; }
        toks.push({ kind: "delim", v: run, open, close, pos: i });
        i += run.length;
        continue;
      }
      buf += s.slice(i, i + run.length); // spaced "*" (e.g. "2 * 3") stays literal
      i += run.length;
      continue;
    }
    buf += s[i++];
  }
  if (buf) toks.push({ kind: "text", v: buf });

  // pair delimiters with a stack
  const role = new Map<number, "open" | "close" | "drop" | "literal">();
  const stack: number[] = [];
  toks.forEach((t, idx) => {
    if (t.kind !== "delim") return;
    const top = stack.length ? toks[stack[stack.length - 1]] as Extract<Tok, { kind: "delim" }> : null;
    if (t.close && top && top.v === t.v) { role.set(stack.pop()!, "open"); role.set(idx, "close"); return; }
    // close an outer pair of the same kind across a mismatched inner opener (e.g. "**a *b**")
    if (t.close) {
      const k = stack.map((j) => toks[j]).findIndex((x) => x.kind === "delim" && x.v === t.v);
      if (k >= 0) { const inner = stack.splice(k); role.set(inner[0], "open"); role.set(idx, "close"); inner.slice(1).forEach((j) => role.set(j, "literal")); return; }
    }
    if (t.open) { stack.push(idx); return; }
    role.set(idx, "literal");
  });
  const lastIdx = toks.length - 1;
  for (const idx of stack) {
    const t = toks[idx] as Extract<Tok, { kind: "delim" }>;
    if (streaming) role.set(idx, idx === lastIdx ? "drop" : "open"); // style the rest until the closer arrives
    else role.set(idx, t.v === "**" ? "drop" : "literal"); // a stray "**" is never shown; a stray "*" is kept
  }
  if (streaming && lastIdx >= 0 && toks[lastIdx].kind === "delim" && role.get(lastIdx) === "literal") role.set(lastIdx, "drop");

  const out: Line = [];
  let strong = 0, em = 0;
  toks.forEach((t, idx) => {
    if (t.kind === "text") { push(t.v); return; }
    const r = role.get(idx);
    if (r === "open") { if (t.v === "**") strong++; else em++; }
    else if (r === "close") { if (t.v === "**") strong = Math.max(0, strong - 1); else em = Math.max(0, em - 1); }
    else if (r === "literal") push(t.v);
  });
  function push(v: string) {
    const span: Span = { text: v };
    if (strong) span.strong = true;
    if (em) span.em = true;
    const prev = out[out.length - 1];
    if (prev && !!prev.strong === !!span.strong && !!prev.em === !!span.em) prev.text += v;
    else out.push(span);
  }
  return out;
}

/** Blocks for a whole answer. */
export function parseMarkdown(text: string, streaming = false): Block[] {
  type ListBlock = Extract<Block, { type: "ul" | "ol" }>;
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: Block[] = [];
  let para: Line[] | null = null;
  let list: ListBlock | null = null;
  let listIndent = 0;
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const st = streaming && i === lines.length - 1;
    if (!raw.trim()) { para = null; list = null; continue; }
    const h = HEADING.exec(raw);
    if (h) { para = null; list = null; blocks.push({ type: "h", line: parseInline(h[1], st) }); continue; }
    const o = ORDERED.exec(raw);
    const b = o ? null : BULLET.exec(raw);
    if (o || b) {
      const indent = (o ? o[1] : b![1]).length;
      const body = parseInline(o ? o[3] : b![2], st);
      // a deeper item under an existing item becomes that item's sub-list
      if (list && indent > listIndent && list.items.length) {
        const item = list.items[list.items.length - 1];
        (item.sub ??= []).push(body);
        continue;
      }
      const kind = o ? "ol" : "ul";
      if (!list || list.type !== kind) {
        para = null;
        list = o ? { type: "ol", start: Number(o[2]) || 1, items: [] } : { type: "ul", items: [] };
        listIndent = indent;
        blocks.push(list);
      }
      list.items.push({ line: body });
      continue;
    }
    // an indented line without a marker continues the previous list item
    if (list && /^\s{2,}\S/.test(raw) && list.items.length) {
      list.items[list.items.length - 1].line.push({ text: " " }, ...parseInline(raw.trim(), st));
      continue;
    }
    list = null;
    if (!para) { para = []; blocks.push({ type: "p", lines: para }); }
    para.push(parseInline(raw.trim(), st));
  }
  return blocks;
}
