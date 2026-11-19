/** Viewer preferences: theme, text size and the rail/chat split. The same keys and rules are applied before first paint
 * by the inline script in app/layout.tsx (PREPAINT below), so React state, storage and <html> never disagree.
 * Every storage access is wrapped: private windows and blocked site data must still render the page. */

export type ThemePref = "system" | "light" | "dark";
export type TextScale = 1 | 1.125;
export interface RailLayout { railW: number | null; collapsed: boolean; touched: boolean }

export const THEME_KEY = "concierge.theme";
export const SCALE_KEY = "concierge.textScale";
export const LAYOUT_KEY = "concierge.layout";
export const LANG_KEY = "concierge.lang";

export const RAIL_MIN = 260;
export const RAIL_MAX = 520;
export const RAIL_COLLAPSED = 56;
export const SEPARATOR_W = 8;
export const CHAT_MIN = 560;
export const SPLIT_MIN_VIEWPORT = 900;
export const AUTO_COLLAPSE_BELOW = 1280;

/** theme-color per resolved theme; matches --bg in globals.css. */
export const THEME_COLOR = { dark: "#0c0b0a", light: "#fdfcfa" } as const;

export function readStore(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
export function writeStore(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch { /* storage blocked: the choice lasts for this page view only */ }
}

export function parseTheme(v: string | null | undefined): ThemePref {
  return v === "light" || v === "dark" ? v : "system";
}
export function parseScale(v: string | null | undefined): TextScale {
  return v === "1.125" || v === "large" ? 1.125 : 1;
}
export function parseLayout(v: string | null | undefined): RailLayout {
  const out: RailLayout = { railW: null, collapsed: false, touched: false };
  if (!v) return out;
  try {
    const o = JSON.parse(v) as Partial<RailLayout>;
    if (typeof o.railW === "number" && o.railW >= RAIL_MIN && o.railW <= RAIL_MAX) out.railW = Math.round(o.railW);
    out.collapsed = o.collapsed === true;
    out.touched = o.touched === true;
  } catch { /* corrupt value: defaults */ }
  return out;
}

/** Default rail width, the same formula as the CSS: clamp(280px, 24vw + 40px, 440px). */
export function defaultRailW(vw: number): number {
  return Math.round(Math.min(440, Math.max(280, vw * 0.24 + 40)));
}
/** Largest rail the viewport allows while the chat keeps >= 560px. */
export function maxRailW(vw: number): number {
  return Math.max(RAIL_MIN, Math.min(RAIL_MAX, vw - CHAT_MIN - SEPARATOR_W));
}

export function resolvedTheme(pref: ThemePref): "light" | "dark" {
  if (pref !== "system") return pref;
  try { return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"; } catch { return "dark"; }
}

/** Point every theme-color meta at the active theme (explicit choice), or back at its own media query (system). */
export function syncThemeColor(pref: ThemePref): void {
  const metas = document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
  metas.forEach((m) => {
    const media = m.getAttribute("media") || "";
    const own = media.indexOf("light") >= 0 ? THEME_COLOR.light : THEME_COLOR.dark;
    m.content = pref === "system" ? own : THEME_COLOR[pref];
  });
}

export function applyTheme(pref: ThemePref): void {
  const d = document.documentElement;
  if (pref === "system") d.removeAttribute("data-theme");
  else d.setAttribute("data-theme", pref);
  syncThemeColor(pref);
}
export function applyScale(s: TextScale): void {
  const d = document.documentElement;
  d.style.setProperty("--text-scale", String(s));
  if (s === 1) d.removeAttribute("data-text-scale");
  else d.setAttribute("data-text-scale", "large");
}
export function applyLayout(l: RailLayout): void {
  const d = document.documentElement;
  if (l.railW === null) d.style.removeProperty("--rail-w");
  else d.style.setProperty("--rail-w", `${l.railW}px`);
  d.setAttribute("data-rail", l.collapsed ? "collapsed" : "open");
}

/**
 * Runs in <head> before first paint. Kept as plain ES5 and self-contained (no imports exist at that point).
 * Order: language (?lang= / toggle / storage / browser), theme, text size, rail layout, theme-color.
 */
export const PREPAINT = `(function(){var d=document.documentElement,ls=null,ss=null;
try{ls=window.localStorage}catch(e){}try{ss=window.sessionStorage}catch(e){}
function g(s,k){try{return s?s.getItem(k):null}catch(e){return null}}
function p(s,k,v){try{if(s)s.setItem(k,v)}catch(e){}}
var l=null,q=null,e=false,sp=null;
try{sp=new URLSearchParams(location.search);q=sp.get('lang');e=sp.get('embed')==='1'}catch(x){}
var stored=g(ls,'${LANG_KEY}'),toggled=g(ss,'${LANG_KEY}.toggled')==='1';
if((q==='ar'||q==='en')&&(e||!toggled)){l=q;if(!e)p(ls,'${LANG_KEY}',q)}else l=stored;
if(l!=='ar'&&l!=='en'){l=(navigator.language||'').toLowerCase().indexOf('ar')===0?'ar':'en'}
d.lang=l;d.dir=l==='ar'?'rtl':'ltr';
if(!e&&sp&&(q==='ar'||q==='en')&&q!==l){try{sp.set('lang',l);history.replaceState(history.state,'',location.pathname+'?'+sp.toString()+location.hash)}catch(x){}}
var t=g(ls,'${THEME_KEY}');if(t==='light'||t==='dark')d.setAttribute('data-theme',t);else t='system';
var sc=g(ls,'${SCALE_KEY}');if(sc==='1.125'||sc==='large'){d.style.setProperty('--text-scale','1.125');d.setAttribute('data-text-scale','large')}
var c=false;try{var o=JSON.parse(g(ls,'${LAYOUT_KEY}')||'null');if(o){if(typeof o.railW==='number'&&o.railW>=${RAIL_MIN}&&o.railW<=${RAIL_MAX})d.style.setProperty('--rail-w',Math.round(o.railW)+'px');c=o.collapsed===true}}catch(x){}
d.setAttribute('data-rail',c?'collapsed':'open');
function tc(){var m=document.querySelectorAll('meta[name="theme-color"]');for(var i=0;i<m.length;i++){var md=m[i].getAttribute('media')||'';var own=md.indexOf('light')>=0?'${THEME_COLOR.light}':'${THEME_COLOR.dark}';m[i].setAttribute('content',t==='light'?'${THEME_COLOR.light}':t==='dark'?'${THEME_COLOR.dark}':own)}}
tc();if(t!=='system')document.addEventListener('DOMContentLoaded',tc);
})();`;
