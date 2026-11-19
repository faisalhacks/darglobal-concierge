"use client";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

export function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="page-shell" style={{ minHeight: "100dvh", display: "flex", flexDirection: "column" }}>
      <SiteHeader />
      <main id="main" className="page" tabIndex={-1}>{children}</main>
      <SiteFooter />
    </div>
  );
}
