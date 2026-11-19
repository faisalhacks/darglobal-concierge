"use client";
import Link from "next/link";
import { useApp } from "./AppContext";

function safeExternal(url: string | null | undefined): string | null {
  if (!url) return null;
  try { const u = new URL(url); return u.protocol === "https:" ? u.toString() : null; } catch { return null; }
}

/** compact: one line on the chat screen (short disclaimer with Privacy inline). */
export function SiteFooter({ compact = false }: { compact?: boolean }) {
  const { t, meta } = useApp();
  const c = meta?.candidate;
  const github = safeExternal(c?.github);
  const linkedin = safeExternal(c?.linkedin);
  const email = c?.email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.email) ? c.email : null;
  const hasCandidate = Boolean(c?.name || github || linkedin || email);
  return (
    <footer className={`site-footer${compact ? " site-footer--compact" : ""}`}>
      <p className="site-footer__disclaimer">
        <span className="site-footer__long">{t.footerInfo} {t.footerDisclaimer}</span>
        <span className="site-footer__short">{t.footerShort}</span>
        {compact && <> <Link className="site-footer__privacy" href="/privacy/">{t.navPrivacy}</Link></>}
      </p>
      <div className="site-footer__row">
        {!compact && <Link href="/privacy/">{t.navPrivacy}</Link>}
        {hasCandidate && (
          <p className="site-footer__candidate">
            {c?.name && <span>{t.footerBuilt} <span lang="en" dir="ltr">{c.name}</span></span>}
            {github && <a href={github} rel="noopener noreferrer" target="_blank">GitHub</a>}
            {linkedin && <a href={linkedin} rel="noopener noreferrer" target="_blank">LinkedIn</a>}
            {email && <a className="site-footer__email" href={`mailto:${email}`} dir="ltr">{email}</a>}
            {email && <a className="site-footer__email-short" href={`mailto:${email}`}>Email</a>}
          </p>
        )}
      </div>
    </footer>
  );
}
