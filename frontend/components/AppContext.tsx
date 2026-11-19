"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getMeta } from "@/lib/api";
import { STRINGS, type Strings } from "@/lib/i18n";
import type { ApiMeta, Lang } from "@/lib/types";

interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: Strings;
  meta: ApiMeta | null;
  metaState: "loading" | "ready" | "error";
}
const AppCtx = createContext<Ctx | null>(null);
const KEY = "concierge.lang";

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  const [meta, setMeta] = useState<ApiMeta | null>(null);
  const [metaState, setMetaState] = useState<Ctx["metaState"]>("loading");

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
  }, []);

  useEffect(() => {
    const el = document.documentElement;
    el.lang = lang;
    el.dir = lang === "ar" ? "rtl" : "ltr";
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

  const value = useMemo(() => ({ lang, setLang, t: STRINGS[lang], meta, metaState }), [lang, setLang, meta, metaState]);
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

export function useApp() {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside AppProvider");
  return c;
}
