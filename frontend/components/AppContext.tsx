"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getMeta } from "@/lib/api";
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
}
const AppCtx = createContext<Ctx | null>(null);
const KEY = "concierge.lang";

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  const [meta, setMeta] = useState<ApiMeta | null>(null);
  const [metaState, setMetaState] = useState<Ctx["metaState"]>("loading");
  const [langResolved, setLangResolved] = useState(false);
  const [resetChat, setResetChatState] = useState<(() => void) | null>(null);
  const setResetChat = useCallback((fn: (() => void) | null) => setResetChatState(() => fn), []);

  useEffect(() => {
    let initial: Lang | null = null;
    try {
      const q = new URLSearchParams(window.location.search).get("lang");
      if (q === "ar" || q === "en") initial = q;
      else {
        const s = window.localStorage.getItem(KEY);
        if (s === "ar" || s === "en") initial = s;
      }
    } catch { /* storage blocked */ }
    if (!initial && typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("ar")) initial = "ar";
    if (initial) setLangState(initial);
    setLangResolved(true);
  }, []);
  // Reveal the page once the language and the corpus meta are settled, or after 1.5 s whatever happens.
  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => { const id = window.setTimeout(() => setTimedOut(true), 1500); return () => window.clearTimeout(id); }, []);
  const ready = timedOut || (langResolved && metaState !== "loading");

  useEffect(() => {
    const el = document.documentElement;
    el.lang = lang;
    el.dir = lang === "ar" ? "rtl" : "ltr";
    // The tab title follows the interface language (the static export ships the English title).
    const EN = "Property Concierge", AR = "المساعد العقاري";
    const cur = document.title;
    document.title = lang === "ar"
      ? cur.replace(EN, AR).replace("DarGlobal · Wasalt", "دار جلوبال · وصلت")
      : cur.replace(AR, EN).replace("دار جلوبال · وصلت", "DarGlobal · Wasalt");
  }, [lang]);

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
  }, []);

  const llmState: LlmState | null = meta
    ? (meta.llm?.state ?? ((meta as { maintenance_mode?: boolean }).maintenance_mode ? "maintenance" : meta.llm_available ? "ok" : "off"))
    : null;
  const value = useMemo(
    () => ({ lang, setLang, t: STRINGS[lang], meta, metaState, llmState, resetChat, setResetChat }),
    [lang, setLang, meta, metaState, llmState, resetChat, setResetChat],
  );
  return (
    <AppCtx.Provider value={value}>
      <div className="app-root" data-ready={ready ? "1" : undefined}>{children}</div>
    </AppCtx.Provider>
  );
}

export function useApp() {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside AppProvider");
  return c;
}
