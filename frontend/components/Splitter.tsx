"use client";
import { useRef } from "react";
import { RAIL_COLLAPSED, RAIL_MAX, RAIL_MIN, maxRailW } from "@/lib/prefs";
import { shellT } from "@/lib/shellStrings";
import { useApp, useRail } from "./AppContext";

/** Below this raw drag width the rail snaps to the 56px strip; between it and 260 the rail holds at 260. */
const SNAP_COLLAPSE = 160;

/**
 * The rail/chat separator (spec 1): a focusable role=separator. Pointer drag with pointer capture follows the pointer
 * 1:1 (no transition while dragging). Keys: Arrow 16px, Shift+Arrow 64px, mirrored in RTL so the arrow moves the line
 * the way it points; Home collapses, End goes to the largest width the chat allows, Enter toggles collapse.
 * Double-click restores the default width. Width and collapse persist (concierge.layout).
 */
export function Splitter() {
  const { t, lang } = useApp();
  const rail = useRail();
  const drag = useRef<{ x: number; w: number; id: number; moved: boolean } | null>(null);
  const rtl = lang === "ar";

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    // No preventDefault: a mouse press focuses the separator without a focus-visible ring; selection is off while dragging.
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, w: rail.collapsed ? RAIL_COLLAPSED : rail.width, id: e.pointerId, moved: false };
    rail.setDragging(true);
  };
  const widthAt = (clientX: number) => {
    const d = drag.current!;
    const dx = clientX - d.x;
    return d.w + (rtl ? -dx : dx);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const raw = widthAt(e.clientX);
    if (!d.moved && Math.abs(raw - d.w) < 2) return;
    d.moved = true;
    if (raw < SNAP_COLLAPSE) { if (!rail.collapsed) rail.setCollapsed(true); return; }
    rail.setWidth(raw, false);
  };
  const end = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const raw = widthAt(e.clientX);
    drag.current = null;
    rail.setDragging(false);
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    if (!d.moved) return;
    if (raw < SNAP_COLLAPSE) rail.setCollapsed(true);
    else rail.setWidth(raw, true);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 64 : 16;
    const grow = rtl ? "ArrowLeft" : "ArrowRight";
    const shrink = rtl ? "ArrowRight" : "ArrowLeft";
    const base = rail.collapsed ? RAIL_MIN - step : rail.width;
    switch (e.key) {
      case grow: rail.setWidth(base + step, true); break;
      case shrink:
        if (rail.collapsed) return;
        rail.setWidth(rail.width - step, true);
        break;
      case "Home": rail.setCollapsed(true); break;
      case "End": rail.setWidth(maxRailW(window.innerWidth), true); break;
      case "Enter": rail.toggle(); break;
      default: return;
    }
    e.preventDefault();
  };

  return (
    <div
      className="splitter"
      role="separator"
      aria-orientation="vertical"
      aria-controls="rail"
      aria-label={shellT(t, lang, "railResize")}
      aria-valuemin={RAIL_MIN}
      aria-valuemax={RAIL_MAX}
      aria-valuenow={rail.collapsed ? RAIL_MIN : rail.width}
      aria-valuetext={rail.collapsed ? shellT(t, lang, "railCollapsedText") : `${rail.width}px`}
      tabIndex={0}
      data-dragging={rail.dragging ? "1" : undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onDoubleClick={rail.reset}
      onKeyDown={onKeyDown}
    />
  );
}
