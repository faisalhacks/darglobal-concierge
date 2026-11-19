"use client";
import { useEffect, useRef, useState } from "react";
import { safeImage } from "@/lib/api";
import s from "./cards.module.css";

/** A collected photo, hot-linked from its original page (owner-approved, SPEC D5), or nothing at all.
 * The frame reserves its aspect ratio while the image loads (no layout shift); on error the whole media block is
 * removed, so a failed or blocked image never leaves an empty frame or a drawn placeholder. */
export function Photo({
  src, alt, ratio = "16 / 10", letterbox = false, className,
}: { src: string | null | undefined; alt: string; ratio?: string; letterbox?: boolean; className?: string }) {
  const safe = safeImage(src);
  const [state, setState] = useState<"loading" | "ok" | "failed">("loading");
  const [portrait, setPortrait] = useState(false);
  const ref = useRef<HTMLImageElement>(null);
  useEffect(() => {
    setState("loading");
    const img = ref.current;
    // An image that failed before React attached onError (cache, blocked request) is caught here.
    if (img && img.complete) setState(img.naturalWidth > 0 ? "ok" : "failed");
  }, [safe]);
  if (!safe || state === "failed") return null;
  return (
    <div className={`${s.media}${className ? ` ${className}` : ""}`} style={{ aspectRatio: ratio }} data-state={state}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        ref={ref}
        src={safe}
        alt={alt}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        className={letterbox && portrait ? s.contain : undefined}
        onLoad={(e) => {
          const im = e.currentTarget;
          if (!im.naturalWidth) { setState("failed"); return; }
          setPortrait(im.naturalHeight > im.naturalWidth);
          setState("ok");
        }}
        onError={() => setState("failed")}
      />
    </div>
  );
}

/** Small decorative-free icons, one stroke weight. Directional ones mirror in RTL via CSS. */
export function ExternalIcon() {
  return (
    <svg className={s.iconDir} width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
export function ChevronIcon() {
  return (
    <svg className={s.iconDir} width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
