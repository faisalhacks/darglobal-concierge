"use client";
import { useRef } from "react";
import { useApp } from "./AppContext";
import { PageToc } from "./PageToc";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/** englishOnly: the page body is English; with Arabic selected, a one-line Arabic notice says so.
 * Layout: one centred frame; "On this page" nav at the inline-start (sticky from 1024px), the reading column beside it. */
export function PageShell({ children, englishOnly = false }: { children: React.ReactNode; englishOnly?: boolean }) {
  const { lang, t } = useApp();
  const bodyRef = useRef<HTMLDivElement>(null);
  return (
    <div className="page-shell">
      <SiteHeader />
      <main id="main" className="page" tabIndex={-1}>
        <PageToc bodyRef={bodyRef} />
        <div className="page__body" ref={bodyRef}>
          {englishOnly && lang === "ar" && t.englishOnly && <p className="en-only" lang="ar" dir="rtl">{t.englishOnly}</p>}
          {children}
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
