"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AUTO_COLLAPSE_BELOW, LAYOUT_KEY, RAIL_MIN, SPLIT_MIN_VIEWPORT, applyLayout, defaultRailW, maxRailW, parseLayout,
  readStore, writeStore, type RailLayout,
} from "./prefs";

export interface RailCtl {
  /** The home page mounts the rail; other pages do not, so the header hides its collapse button there. */
  present: boolean;
  setPresent: (b: boolean) => void;
  /** Shown state: the user's choice, or an automatic collapse after the first answer on a narrow desktop. */
  collapsed: boolean;
  /** Effective expanded width in px (stored or default, clamped so the chat keeps 560px). */
  width: number;
  max: number;
  dragging: boolean;
  setDragging: (b: boolean) => void;
  /** Live width during a drag (no storage write); commit=true persists it. */
  setWidth: (px: number, commit?: boolean) => void;
  setCollapsed: (b: boolean) => void;
  toggle: () => void;
  reset: () => void;
  /** Called once per conversation when the first answer completes. */
  onFirstAnswer: () => void;
  /** Called when the conversation is cleared. */
  onConversationCleared: () => void;
}

export function useRailLayout(): RailCtl {
  // SSR and first client render use defaults; the pre-paint script already put the stored values on <html>,
  // so CSS lays the split out correctly before React reads them back here.
  const [layout, setLayout] = useState<RailLayout>({ railW: null, collapsed: false, touched: false });
  const [auto, setAuto] = useState(false);
  const [vw, setVw] = useState(1440);
  const [present, setPresent] = useState(false);
  const [dragging, setDraggingState] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLayout(parseLayout(readStore(LAYOUT_KEY)));
    setLoaded(true);
    const onResize = () => setVw(window.innerWidth);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const collapsed = layout.collapsed || auto;
  useEffect(() => {
    if (!loaded) return;
    applyLayout({ ...layout, collapsed });
  }, [loaded, layout, collapsed]);

  const persist = useCallback((l: RailLayout) => {
    writeStore(LAYOUT_KEY, JSON.stringify({ railW: l.railW, collapsed: l.collapsed, touched: l.touched }));
  }, []);

  const max = maxRailW(vw);
  const width = Math.max(RAIL_MIN, Math.min(max, layout.railW ?? defaultRailW(vw)));

  const setWidth = useCallback((px: number, commit = false) => {
    const w = Math.round(Math.max(RAIL_MIN, Math.min(maxRailW(window.innerWidth), px)));
    setAuto(false);
    setLayout(() => {
      const next = { railW: w, collapsed: false, touched: true };
      if (commit) persist(next);
      return next;
    });
  }, [persist]);

  const setCollapsed = useCallback((b: boolean) => {
    setAuto(false);
    setLayout((prev) => { const next = { ...prev, collapsed: b, touched: true }; persist(next); return next; });
  }, [persist]);

  const toggle = useCallback(() => setCollapsed(!collapsed), [collapsed, setCollapsed]);

  const reset = useCallback(() => {
    setAuto(false);
    setLayout(() => { const next = { railW: null, collapsed: false, touched: true }; persist(next); return next; });
  }, [persist]);

  const setDragging = useCallback((b: boolean) => {
    setDraggingState(b);
    try {
      if (b) document.documentElement.setAttribute("data-rail-dragging", "");
      else document.documentElement.removeAttribute("data-rail-dragging");
    } catch { /* ignore */ }
  }, []);

  const touchedRef = useRef(layout.touched);
  touchedRef.current = layout.touched;
  const collapsedRef = useRef(collapsed);
  collapsedRef.current = collapsed;

  const onFirstAnswer = useCallback(() => {
    const w = window.innerWidth;
    if (w >= SPLIT_MIN_VIEWPORT && w < AUTO_COLLAPSE_BELOW && !touchedRef.current && !collapsedRef.current) setAuto(true);
  }, []);
  const onConversationCleared = useCallback(() => setAuto(false), []);

  return useMemo(() => ({
    present, setPresent, collapsed, width, max, dragging, setDragging, setWidth, setCollapsed, toggle, reset,
    onFirstAnswer, onConversationCleared,
  }), [present, collapsed, width, max, dragging, setDragging, setWidth, setCollapsed, toggle, reset, onFirstAnswer, onConversationCleared]);
}
