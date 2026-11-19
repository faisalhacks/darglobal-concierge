"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useApp } from "./AppContext";

export function Mark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="mark">
      <path d="M12 2.5 21.5 12 12 21.5 2.5 12Z" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M12 8 16 12 12 16 8 12Z" fill="currentColor" />
    </svg>
  );
}

/** The one place the model state is announced. Fixed height, present from first paint, so it never shifts layout. */
export function StatusLine() {
  const { t, llmState, metaState } = useApp();
  const [online, setOnline] = useState(true);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    setOnline(navigator.onLine);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); };
  }, []);
  let text: string;
  let tone = "quiet";
  if (!online) { text = t.offline; tone = "warn"; }
  else if (metaState === "loading") text = t.statusLoading;
  else if (metaState === "error") { text = t.statUnavailable; tone = "warn"; }
  else {
    text = { ok: t.statusOk, quota: t.statusQuota, cooling: t.statusCooling, off: t.statusOff, maintenance: t.statusMaintenance }[llmState ?? "off"];
  }
  return (
    <p className={`status-line status-line--${tone}`} role="status" data-llm={llmState ?? "unknown"}>
      <span className="status-line__text">{text}</span>
    </p>
  );
}

export function SiteHeader({ showStatus = true }: { showStatus?: boolean }) {
  const { t, lang, setLang, resetChat } = useApp();
  const path = usePathname() || "/";
  const nav = [
    { href: "/how-it-works/", label: t.navHow, short: t.navHowShort },
    { href: "/evals/", label: t.navEvals, short: t.navEvals },
  ];
  const other = lang === "en" ? "ar" : "en";
  return (
    <header className="site-header">
      <a className="skip" href="#main">{t.skip}</a>
      <div className="site-header__bar">
        <Link href="/" className="brand" aria-label={`${t.brand}. ${t.brandSub}`}>
          <Mark />
          <span className="brand__text">
            <span className="brand__name">{t.brand}</span>
            <span className="brand__sub">{t.brandSub}</span>
          </span>
        </Link>
        <nav className="site-nav" aria-label="Primary">
          {resetChat && (
            <button type="button" className="site-nav__link site-nav__new" onClick={resetChat} aria-label={t.newChat}>
              <svg className="site-nav__icon" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
              <span className="nav-long">{t.newChat}</span>
            </button>
          )}
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className={`site-nav__link${n.href === "/evals/" ? " site-nav__link--secondary" : ""}`} aria-label={n.label} aria-current={path.startsWith(n.href.slice(0, -1)) ? "page" : undefined}>
              <span className="nav-long">{n.label}</span><span className="nav-short" aria-hidden="true">{n.short}</span>
            </Link>
          ))}
          <button
            type="button"
            className="lang-toggle"
            lang={other}
            dir={other === "ar" ? "rtl" : "ltr"}
            aria-label={t.langSwitchLabel}
            onClick={() => setLang(other)}
          >
            {t.langSwitch}
          </button>
        </nav>
      </div>
      {showStatus && <StatusLine />}
    </header>
  );
}
