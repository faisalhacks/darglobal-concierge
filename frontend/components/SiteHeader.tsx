"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { shellT, type ShellKey } from "@/lib/shellStrings";
import type { TextScale, ThemePref } from "@/lib/prefs";
import { useApp, useRail } from "./AppContext";
import { AboutSheet } from "./AboutSheet";

export function Mark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="mark">
      <path d="M12 2.5 21.5 12 12 21.5 2.5 12Z" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M12 8 16 12 12 16 8 12Z" fill="currentColor" />
    </svg>
  );
}

/** Small line icons, 20px, currentColor. None is directional, so none mirrors in RTL. */
export function Icon({ name }: { name: "appearance" | "menu" | "close" | "sidebar" | "plus" | "info" | "book" }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg className="icon" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {name === "appearance" && (<><circle cx="12" cy="12" r="8.25" {...p} /><path d="M12 3.75a8.25 8.25 0 0 1 0 16.5Z" fill="currentColor" /></>)}
      {name === "menu" && <path d="M4 7h16M4 12h16M4 17h16" {...p} />}
      {name === "close" && <path d="M6 6l12 12M18 6 6 18" {...p} />}
      {name === "sidebar" && (<><rect x="3.75" y="4.75" width="16.5" height="14.5" rx="2" {...p} /><path d="M9.25 4.75v14.5" {...p} /></>)}
      {name === "plus" && <path d="M12 5v14M5 12h14" {...p} />}
      {name === "info" && (<><circle cx="12" cy="12" r="8.25" {...p} /><path d="M12 11v5.25M12 7.75v.01" {...p} /></>)}
      {name === "book" && <path d="M4.75 5.75A1.75 1.75 0 0 1 6.5 4h12.75v14.5H6.5a1.75 1.75 0 0 0-1.75 1.75Zm0 14.5V5.75M8.5 8h7" {...p} />}
    </svg>
  );
}

/** A radiogroup of buttons with roving tabindex: arrows move and select (wrapping), Home/End jump. */
function Radios<V extends string | number>({ label, value, options, onChange }: {
  label: string; value: V; options: { value: V; label: string }[]; onChange: (v: V) => void;
}) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const rtl = document.documentElement.dir === "rtl";
    let n = -1;
    if (e.key === "ArrowDown" || e.key === (rtl ? "ArrowLeft" : "ArrowRight")) n = (i + 1) % options.length;
    else if (e.key === "ArrowUp" || e.key === (rtl ? "ArrowRight" : "ArrowLeft")) n = (i - 1 + options.length) % options.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = options.length - 1;
    if (n < 0) return;
    e.preventDefault();
    onChange(options[n].value);
    refs.current[n]?.focus();
  };
  return (
    <div className="appearance__group">
      <p className="appearance__label" id={id}>{label}</p>
      <div role="radiogroup" aria-labelledby={id} className="appearance__radios">
        {options.map((o, i) => {
          const on = o.value === value;
          return (
            <button
              key={String(o.value)}
              ref={(el) => { refs.current[i] = el; }}
              type="button"
              role="radio"
              aria-checked={on}
              tabIndex={on ? 0 : -1}
              className="appearance__radio"
              data-value={String(o.value)}
              onClick={() => onChange(o.value)}
              onKeyDown={(e) => onKey(e, i)}
            >
              <span className="appearance__dot" aria-hidden="true" />
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function AppearanceControls() {
  const { t, lang, theme, setTheme, textScale, setTextScale } = useApp();
  const s = (k: ShellKey) => shellT(t, lang, k);
  return (
    <>
      <Radios<ThemePref>
        label={s("themeLabel")}
        value={theme}
        onChange={setTheme}
        options={[
          { value: "system", label: s("themeSystem") },
          { value: "light", label: s("themeLight") },
          { value: "dark", label: s("themeDark") },
        ]}
      />
      <Radios<TextScale>
        label={s("textSizeLabel")}
        value={textScale}
        onChange={setTextScale}
        options={[
          { value: 1, label: s("textSizeDefault") },
          { value: 1.125, label: s("textSizeLarge") },
        ]}
      />
    </>
  );
}

/** Popover behaviour shared by the Appearance menu and the phone menu: Esc closes and returns focus to the trigger,
 * a click or focus outside closes, opening moves focus into the panel. */
function usePopover(preferChecked: boolean) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const panel = useRef<HTMLDivElement | null>(null);
  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }, []);
  useEffect(() => {
    if (!open) return;
    const p = panel.current;
    const first = (preferChecked ? p?.querySelector<HTMLElement>('[role="radio"][aria-checked="true"]') : null)
      ?? p?.querySelector<HTMLElement>("a, button");
    first?.focus();
    const onDown = (e: PointerEvent) => {
      const n = e.target as Node;
      if (!panel.current?.contains(n) && !trigger.current?.contains(n)) close(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); close(true); } };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, close, preferChecked]);
  const onBlur = (e: React.FocusEvent) => {
    const next = e.relatedTarget as Node | null;
    if (next && !panel.current?.contains(next) && !trigger.current?.contains(next)) close(false);
  };
  return { open, setOpen, close, trigger, panel, onBlur };
}

function AppearanceMenu() {
  const { t, lang } = useApp();
  const id = useId();
  const pop = usePopover(true);
  const label = shellT(t, lang, "appearance");
  return (
    <div className="appearance hdr-wide" onBlur={pop.onBlur}>
      <button
        ref={pop.trigger}
        type="button"
        className="hdr-icon"
        aria-label={label}
        title={label}
        aria-haspopup="true"
        aria-expanded={pop.open}
        aria-controls={id}
        onClick={() => pop.setOpen(!pop.open)}
      >
        <Icon name="appearance" />
      </button>
      <div ref={pop.panel} id={id} className="popover appearance__panel" role="group" aria-label={label} hidden={!pop.open}>
        {pop.open && <AppearanceControls />}
      </div>
    </div>
  );
}

function PhoneMenu({ nav }: { nav: { href: string; label: string }[] }) {
  const { t, lang, resetChat, openAbout } = useApp();
  const id = useId();
  const pop = usePopover(false);
  const s = (k: ShellKey) => shellT(t, lang, k);
  const path = usePathname() || "/";
  return (
    <div className="phone-menu hdr-narrow" onBlur={pop.onBlur}>
      <button
        ref={pop.trigger}
        type="button"
        className="hdr-icon"
        aria-label={pop.open ? s("menuClose") : s("menuOpen")}
        aria-expanded={pop.open}
        aria-controls={id}
        onClick={() => pop.setOpen(!pop.open)}
      >
        <Icon name={pop.open ? "close" : "menu"} />
      </button>
      <div ref={pop.panel} id={id} className="popover phone-menu__panel" hidden={!pop.open}>
        {pop.open && (
          <>
            <nav aria-label={t.navChat} className="phone-menu__nav">
              {resetChat && (
                <button type="button" className="phone-menu__item" onClick={() => { pop.close(false); resetChat(); }}>
                  <Icon name="plus" />{t.newChat}
                </button>
              )}
              {nav.map((n) => (
                <Link key={n.href} href={n.href} className="phone-menu__item" onClick={() => pop.close(false)}
                  aria-current={path.startsWith(n.href.slice(0, -1)) ? "page" : undefined}>
                  {n.label}
                </Link>
              ))}
              <button type="button" className="phone-menu__item"
                onClick={() => { const trg = pop.trigger.current; pop.close(false); openAbout(trg); }}>
                <Icon name="info" />{s("aboutSources")}
              </button>
            </nav>
            <div className="phone-menu__appearance" role="group" aria-label={s("appearance")}>
              <AppearanceControls />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function RailToggle() {
  const { t, lang } = useApp();
  const rail = useRail();
  if (!rail.present) return null;
  const label = shellT(t, lang, rail.collapsed ? "railExpand" : "railCollapse");
  return (
    <button type="button" className="hdr-icon hdr-wide rail-toggle" aria-controls="rail" aria-expanded={!rail.collapsed}
      aria-label={label} title={label} onClick={rail.toggle}>
      <Icon name="sidebar" />
    </button>
  );
}

/** showStatus is accepted for older call sites and ignored: the status strip is gone (spec 1, chrome budget). */
export function SiteHeader(_props: { showStatus?: boolean } = {}) {
  const { t, lang, setLang, resetChat } = useApp();
  const path = usePathname() || "/";
  const nav = [
    { href: "/how-it-works/", label: t.navHow },
    { href: "/evals/", label: t.navEvals },
  ];
  const other = lang === "en" ? "ar" : "en";
  return (
    <header className="site-header">
      <a className="skip" href="#main">{t.skip}</a>
      <div className="site-header__bar">
        <RailToggle />
        <Link href="/" className="brand">
          <Mark />
          <span className="brand__text">
            <span className="brand__name">{t.brand}</span>
            <span className="brand__sub">{t.brandSub}</span>
          </span>
        </Link>
        <nav className="site-nav hdr-wide" aria-label={t.navChat}>
          {resetChat && (
            <button type="button" className="site-nav__link site-nav__new" onClick={resetChat}>
              <Icon name="plus" /><span>{t.newChat}</span>
            </button>
          )}
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className="site-nav__link" aria-current={path.startsWith(n.href.slice(0, -1)) ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="site-header__tools">
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
          <AppearanceMenu />
          <PhoneMenu nav={nav} />
        </div>
      </div>
      <AboutSheet />
    </header>
  );
}
