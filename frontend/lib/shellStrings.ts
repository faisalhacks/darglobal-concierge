import type { Lang } from "./types";
import type { Strings } from "./i18n";

/**
 * Labels for the shell controls (appearance menu, phone menu, rail split, About sheet, one-line footer).
 * lib/i18n.ts is owned by the copy lane; when it defines a key with the same name, that string wins (see shellT).
 * Until then these are the EN/AR labels. Arabic copy still needs a native reader's sign-off (NEEDS-HUMAN, item 21).
 */
const EN = {
  appearance: "Appearance",
  themeLabel: "Theme",
  themeSystem: "System",
  themeLight: "Light",
  themeDark: "Dark",
  textSizeLabel: "Text size",
  textSizeDefault: "Default",
  textSizeLarge: "Large",
  chatWidthLabel: "Chat width",
  chatWidthComfortable: "Comfortable",
  chatWidthWide: "Wide",
  themeButton: "Theme",
  railResizeTip: "Drag to resize",
  buildLabel: "Build",
  menuOpen: "Menu",
  menuClose: "Close menu",
  aboutSources: "About and sources",
  onThisPage: "On this page",
  aboutClose: "Close",
  railCollapse: "Collapse sidebar",
  railExpand: "Expand sidebar",
  railResize: "Resize sidebar",
  railCollapsedText: "Sidebar collapsed",
  railGuardrails: "For reviewers: test the guardrails",
  railPhotoFrom: "From its DarGlobal project page",
  /** One sentence; the only disclaimer on the first screen (spec 1, 8). */
  footerLine: "Not an official channel or advice.",
  footerLineWide: "Not an official channel or advice.",
} as const;

export type ShellKey = keyof typeof EN;

const AR: Record<ShellKey, string> = {
  appearance: "المظهر",
  themeLabel: "السمة",
  themeSystem: "تلقائي",
  themeLight: "فاتح",
  themeDark: "داكن",
  textSizeLabel: "حجم النص",
  textSizeDefault: "افتراضي",
  textSizeLarge: "كبير",
  chatWidthLabel: "عرض المحادثة",
  chatWidthComfortable: "مريح",
  chatWidthWide: "واسع",
  themeButton: "المظهر",
  railResizeTip: "اسحب لتغيير العرض",
  buildLabel: "الإصدار",
  menuOpen: "القائمة",
  menuClose: "أغلق القائمة",
  onThisPage: "في هذه الصفحة",
  aboutSources: "عن المساعد والمصادر",
  aboutClose: "إغلاق",
  railCollapse: "طيّ الشريط الجانبي",
  railExpand: "افتح الشريط الجانبي",
  railResize: "تغيير عرض الشريط الجانبي",
  railCollapsedText: "الشريط الجانبي مطويّ",
  railGuardrails: "للمراجعين: اختبر ضوابط الحماية",
  railPhotoFrom: "من صفحة المشروع على موقع دار جلوبال",
  footerLine: "ليست قناة رسمية ولا تقدّم نصيحة.",
  footerLineWide: "ليست قناة رسمية ولا تقدّم نصيحة.",
};

const TABLE: Record<Lang, Record<ShellKey, string>> = { en: EN, ar: AR };

export function shellT(t: Strings, lang: Lang, key: ShellKey): string {
  const own = (t as unknown as Record<string, unknown>)[key];
  return typeof own === "string" && own ? own : TABLE[lang][key];
}
