"use client";
import { useApp } from "./AppContext";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

/** englishOnly: the page body is English; with Arabic selected, a one-line Arabic notice says so. */
export function PageShell({ children, englishOnly = false }: { children: React.ReactNode; englishOnly?: boolean }) {
  const { lang, t } = useApp();
  return (
    <div className="page-shell" style={{ minHeight: "100dvh", display: "flex", flexDirection: "column" }}>
      <SiteHeader showStatus={false} />
      <main id="main" className="page" tabIndex={-1}>
        {englishOnly && lang === "ar" && t.englishOnly && <p className="en-only" lang="ar" dir="rtl">{t.englishOnly}</p>}
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
