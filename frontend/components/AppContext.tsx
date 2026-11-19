"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { getMeta } from "@/lib/api";
import {
  LANG_KEY, SCALE_KEY, THEME_KEY, applyScale, applyTheme, parseScale, parseTheme, readStore, syncThemeColor, writeStore,
  type TextScale, type ThemePref,
} from "@/lib/prefs";
import { useRailLayout, type RailCtl } from "@/lib/useRailLayout";
import { STRINGS, type Strings } from "@/lib/i18n";
import type { ApiMeta, Lang, LlmState } from "@/lib/types";

interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: Strings;
  meta: ApiMeta | null;
  metaState: "loading" | "ready" | "error";
  /** Effective model state: C2 meta.llm.state, else derived from the older llm_available flag. */
  llmState: LlmState | null;
  /** Set by the chat while a conversation exists, so the header can offer "New conversation". */
  resetChat: (() => void) | null;
  setResetChat: (fn: (() => void) | null) => void;
  /** Appearance: "system" leaves html[data-theme] unset so CSS follows prefers-color-scheme. */
  theme: ThemePref;
  setTheme: (t: ThemePref) => void;
  textScale: TextScale;
  setTextScale: (s: TextScale) => void;
  /** About/sources sheet: open it from any trigger; focus returns to that trigger on close. */
  aboutOpen: boolean;
  openAbout: (trigger?: HTMLElement | null) => void;
  closeAbout: () => void;
  aboutTrigger: React.MutableRefObject<HTMLElement | null>;
}
const AppCtx = createContext<Ctx | null>(null);
// Separate context: drag updates re-render only the split, header button and rail, never the chat.
const RailCtx = createContext<RailCtl | null>(null);
const KEY = LANG_KEY;

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  const [meta, setMeta] = useState<ApiMeta | null>(null);
  const [metaState, setMetaState] = useState<Ctx["metaState"]>("loading");
  const [langResolved, setLangResolved] = useState(false);
  const [resetChat, setResetChatState] = useState<(() => void) | null>(null);
  const setResetChat = useCallback((fn: (() => void) | null) => setResetChatState(() => fn), []);
  const [theme, setThemeState] = useState<ThemePref>("system");
  const [textScale, setScaleState] = useState<TextScale>(1);
  const rail = useRailLayout();
  const [aboutOpen, setAboutOpen] = useState(false);
  const aboutTrigger = useRef<HTMLElement | null>(null);

  useEffect(() => {
    // The pre-paint script already applied these to <html>; mirror them into state (no DOM write, so no flash).
    setThemeState(parseTheme(readStore(THEME_KEY)));
    setScaleState(parseScale(readStore(SCALE_KEY)));
  }, []);
  useEffect(() => {
    // System mode follows the OS live; keep theme-color in step.
    if (theme !== "system") return;
    let mq: MediaQueryList | null = null;
    try { mq = window.matchMedia("(prefers-color-scheme: light)"); } catch { return; }
    const on = () => syncThemeColor("system");
    mq.addEventListener?.("change", on);
    return () => mq?.removeEventListener?.("change", on);
  }, [theme]);
  const setTheme = useCallback((t: ThemePref) => {
    setThemeState(t);
    applyTheme(t);
    writeStore(THEME_KEY, t);
  }, []);
  const setTextScale = useCallback((sc: TextScale) => {
    setScaleState(sc);
    applyScale(sc);
    writeStore(SCALE_KEY, sc === 1 ? "1" : "1.125");
  }, []);
  const openAbout = useCallback((trigger?: HTMLElement | null) => {
    aboutTrigger.current = trigger ?? (document.activeElement as HTMLElement | null);
    setAboutOpen(true);
  }, []);
  const closeAbout = useCallback(() => setAboutOpen(false), []);

  useEffect(() => {
    // The inline script in app/layout.tsx already resolved the language (?lang= > stored choice > browser) onto
    // <html lang>; read it from there so the shell, the chat and <html dir> can never disagree.
    const fromHtml = document.documentElement.lang;
    let initial: Lang | null = fromHtml === "ar" || fromHtml === "en" ? fromHtml : null;
    if (!initial) {
      try {
        const q = new URLSearchParams(window.location.search).get("lang");
        const s = window.localStorage.getItem(KEY);
        initial = q === "ar" || q === "en" ? q : s === "ar" || s === "en" ? s : null;
      } catch { /* storage blocked */ }
    }
    if (!initial && typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("ar")) initial = "ar";
    if (initial) setLangState(initial);
    setLangResolved(true);
  }, []);
  // Reveal the page once the language and the corpus meta are settled, or after 1.5 s whatever happens.
  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => { const id = window.setTimeout(() => setTimedOut(true), 1500); return () => window.clearTimeout(id); }, []);
  const ready = timedOut || (langResolved && metaState !== "loading");

  useEffect(() => {
    // Before resolution the state is the SSR default ("en"); writing it would flip an Arabic page to LTR for a frame.
    if (!langResolved) return;
    const el = document.documentElement;
    el.lang = lang;
    el.dir = lang === "ar" ? "rtl" : "ltr";
    // The tab title follows the interface language (the static export ships the English title).
    const EN = "Property Concierge", AR = "المساعد العقاري";
    const cur = document.title;
    document.title = lang === "ar"
      ? cur.replace(EN, AR).replace("DarGlobal · Wasalt", "دار جلوبال · وصلت")
      : cur.replace(AR, EN).replace("دار جلوبال · وصلت", "DarGlobal · Wasalt");
  }, [lang, langResolved]);

  useEffect(() => {
    const ac = new AbortController();
    getMeta(ac.signal)
      .then((m) => { setMeta(m); setMetaState("ready"); })
      .catch((e) => { if (!ac.signal.aborted) { console.warn(e); setMetaState("error"); } });
    return () => ac.abort();
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { window.localStorage.setItem(KEY, l); } catch { /* ignore */ }
    // A toggle outranks a ?lang= already in the address bar for the rest of this tab's session, so a reload keeps the
    // chosen language. (Rewriting the URL instead is not an option: Next remounts the page on a search change, which
    // would wipe the conversation.) A fresh tab or a shared link still honours ?lang=.
    try { window.sessionStorage.setItem(KEY + ".toggled", "1"); } catch { /* ignore */ }
    // ?lang=, storage and state are one source of truth: rewrite the address in place (history API, no navigation,
    // so the conversation survives). Not inside the embedded widget, whose URL belongs to the host page.
    try {
      const u = new URL(window.location.href);
      if (u.searchParams.get("embed") !== "1") {
        u.searchParams.set("lang", l);
        window.history.replaceState(window.history.state, "", u.pathname + u.search + u.hash);
      }
    } catch { /* ignore */ }
  }, []);

  const llmState: LlmState | null = meta
    ? (meta.llm?.state ?? ((meta as { maintenance_mode?: boolean }).maintenance_mode ? "maintenance" : meta.llm_available ? "ok" : "off"))
    : null;
  const value = useMemo(
    () => ({
      lang, setLang, t: STRINGS[lang], meta, metaState, llmState, resetChat, setResetChat,
      theme, setTheme, textScale, setTextScale, aboutOpen, openAbout, closeAbout, aboutTrigger,
    }),
    [lang, setLang, meta, metaState, llmState, resetChat, setResetChat, theme, setTheme, textScale, setTextScale,
      aboutOpen, openAbout, closeAbout],
  );
  return (
    <AppCtx.Provider value={value}>
      <RailCtx.Provider value={rail}>
        <div className="app-root" data-ready={ready ? "1" : undefined}>{children}</div>
      </RailCtx.Provider>
    </AppCtx.Provider>
  );
}

export function useApp() {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside AppProvider");
  return c;
}

export function useRail() {
  const c = useContext(RailCtx);
  if (!c) throw new Error("useRail outside AppProvider");
  return c;
}
