"use client";
import Link from "next/link";
import { shellT } from "@/lib/shellStrings";
import { useApp } from "./AppContext";

function safeExternal(url: string | null | undefined): string | null {
  if (!url) return null;
  try { const u = new URL(url); return u.protocol === "https:" ? u.toString() : null; } catch { return null; }
}

/**
 * compact (home): one line, min-height 40px, on the empty state only (the home shell hides it during a conversation,
 * where the line under the composer takes over). One disclaimer sentence, short on phones, plus Privacy and, from
 * 600px, the candidate's links. Full (content pages): the longer disclaimer and the same links.
 */
export function SiteFooter({ compact = false }: { compact?: boolean }) {
  const { t, lang, meta } = useApp();
  const c = meta?.candidate;
  const github = safeExternal(c?.github);
  const linkedin = safeExternal(c?.linkedin);
  const email = c?.email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.email) ? c.email : null;
  const hasCandidate = Boolean(c?.name || github || linkedin || email);
  const candidate = hasCandidate && (
    <p className="site-footer__candidate">
      {c?.name && <span>{t.footerBuilt} <bdi lang="en" dir="ltr">{c.name}</bdi></span>}
      {github && <a href={github} rel="noopener noreferrer" target="_blank">GitHub</a>}
      {linkedin && <a href={linkedin} rel="noopener noreferrer" target="_blank">LinkedIn</a>}
      {email && <a className="site-footer__email" href={`mailto:${email}`} dir="ltr">{email}</a>}
    </p>
  );
  if (compact) {
    return (
      <footer className="site-footer site-footer--line">
        <p className="site-footer__disclaimer">
          <span className="site-footer__short">{shellT(t, lang, "footerLine")}</span>
          <span className="site-footer__wide">{shellT(t, lang, "footerLineWide")}</span>
        </p>
        <Link className="site-footer__privacy" href="/privacy/">{t.navPrivacy}</Link>
        {candidate}
      </footer>
    );
  }
  return (
    <footer className="site-footer">
      <p className="site-footer__disclaimer">{t.footerInfo} {t.footerDisclaimer}</p>
      <div className="site-footer__row">
        <Link href="/privacy/">{t.navPrivacy}</Link>
        {candidate}
      </div>
    </footer>
  );
}
