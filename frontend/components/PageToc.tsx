"use client";
import { useEffect, useState, type RefObject } from "react";
import { useApp } from "./AppContext";
import { shellT } from "@/lib/shellStrings";

interface Item { id: string; label: string }

/** "On this page": built from the h2 of each top-level section in the page body, so it follows whatever the page
 * renders (evals sections arrive after the report loads). Sticky at the inline-start from 1024px; below that it is
 * a compact list above the content. The current section is marked with aria-current, never by colour alone. */
export function PageToc({ bodyRef }: { bodyRef: RefObject<HTMLElement | null> }) {
  const { t, lang } = useApp();
  const [items, setItems] = useState<Item[]>([]);
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    const scan = () => {
      const next: Item[] = [];
      body.querySelectorAll<HTMLElement>("section:not(.stress--rail)").forEach((sec, i) => {
        const h = sec.querySelector(":scope > h2");
        if (!h || !h.textContent) return;
        if (!sec.id) sec.id = `sec-${i + 1}`;
        next.push({ id: sec.id, label: h.textContent.trim() });
      });
      setItems((prev) => (prev.length === next.length && prev.every((p, k) => p.id === next[k].id && p.label === next[k].label) ? prev : next));
    };
    scan();
    let mo: MutationObserver | undefined;
    try { mo = new MutationObserver(scan); mo.observe(body, { childList: true, subtree: true, characterData: true }); } catch { /* no live updates */ }
    return () => mo?.disconnect();
  }, [bodyRef, lang]);

  useEffect(() => {
    if (!items.length || typeof IntersectionObserver === "undefined") return;
    const seen = new Map<string, boolean>();
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) seen.set(e.target.id, e.isIntersecting);
      const first = items.find((it) => seen.get(it.id));
      if (first) setCurrent(first.id);
    }, { rootMargin: "0px 0px -60% 0px" });
    items.forEach((it) => { const el = document.getElementById(it.id); if (el) io.observe(el); });
    return () => io.disconnect();
  }, [items]);

  if (items.length < 2) return null;
  const label = shellT(t, lang, "onThisPage");
  return (
    <nav className="page-toc" aria-labelledby="page-toc-h">
      <p className="page-toc__title" id="page-toc-h">{label}</p>
      <ol className="page-toc__list">
        {items.map((it) => (
          <li key={it.id}>
            <a href={`#${it.id}`} aria-current={current === it.id ? "location" : undefined}>{it.label}</a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
