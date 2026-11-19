"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApp } from "./AppContext";

export function Mark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="mark">
      <path d="M12 2.5 21.5 12 12 21.5 2.5 12Z" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M12 8 16 12 12 16 8 12Z" fill="currentColor" />
    </svg>
  );
}

export function SiteHeader() {
  const { t, lang, setLang } = useApp();
  const path = usePathname() || "/";
  const nav = [
    { href: "/how-it-works/", label: t.navHow },
    { href: "/evals/", label: t.navEvals, secondary: true },
  ];
  return (
    <header className="site-header">
      <a className="skip" href="#main">{t.skip}</a>
      <div className="site-header__bar">
        <Link href="/" className="brand" aria-label={`${t.brand}, ${t.brandSites}`}>
          <Mark />
          <span className="brand__name">{t.brand}</span>
          <span className="brand__sites">{t.brandSites}</span>
        </Link>
        <nav className="site-nav" aria-label="Primary">
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className={`site-nav__link${"secondary" in n ? " site-nav__link--secondary" : ""}`} aria-current={path.startsWith(n.href.slice(0, -1)) ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
          <div className="lang-toggle" role="group" aria-label={t.langToggleLabel}>
            <button type="button" lang="en" aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
            <button type="button" lang="ar" aria-pressed={lang === "ar"} onClick={() => setLang("ar")}>ع</button>
          </div>
        </nav>
      </div>
      <p className="site-header__notice">{t.prototype}</p>
    </header>
  );
}
