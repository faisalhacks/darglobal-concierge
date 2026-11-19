// Lane C (conversation) interface strings: composer, welcome, scroll, turn action row.
// Kept in their own module so lane F (i18n.ts) can merge them without a write collision; both languages always carry
// the same keys (checked by `satisfies` below). Answer text itself is server-side.
import type { Lang } from "./types";

const arSeconds = (n: number) =>
  n === 1 ? "ثانية واحدة" : n === 2 ? "ثانيتين" : n >= 3 && n <= 10 ? `${n} ثوانٍ` : `${n} ثانية`;
const arMinutes = (n: number) =>
  n === 1 ? "دقيقة واحدة" : n === 2 ? "دقيقتين" : n >= 3 && n <= 10 ? `${n} دقائق` : `${n} دقيقة`;

const en = {
  // Welcome (empty state)
  welcomeHeadline: "Sourced answers on DarGlobal projects and Wasalt homes",
  welcomeHeadlineWasalt: "Sourced answers on Wasalt projects and homes in Saudi Arabia",
  welcomeChipsLabel: "Questions to start with",
  welcomeChips: [
    "Projects in Oman",
    "Tell me about Trump Tower Jeddah",
    "Compare Trump Tower Jeddah and Neptune",
    "20% down on 2,000,000 SAR",
  ],
  welcomePhotoCaption: (name: string) => `${name}. Photo: DarGlobal project page`,

  // Composer
  composerLabel: "Your question",
  send: "Send",
  stop: "Stop",
  stopLabel: "Stop the answer",
  rateLimited: (s: number) =>
    s >= 90
      ? `Too many questions in a short time. You can ask again in about ${Math.round(s / 60)} minutes.`
      : `Too many questions in a short time. You can ask again in ${s} ${s === 1 ? "second" : "seconds"}.`,
  rateLimitedDone: "You can ask again now.",
  legalLine: "Not an official channel or advice.",
  tooLong: "Questions can be up to 1,000 characters. Shorten it to send.",
  charsLeft: (n: number) => `${n} ${n === 1 ? "character" : "characters"} left`,
  privacy: "Privacy",

  // Scroll
  jumpLatest: "Jump to the latest message",

  // Turn states
  notAnswered: "Not answered",
  answerReady: "Answer ready.",

  // Action row
  actionsLabel: "Answer actions",
  copy: "Copy answer",
  copied: "Copied",
  retry: "Ask again",
  helpful: "Helpful",
  notHelpful: "Not helpful",
  feedbackLocal: "Thanks. Your rating stays in this browser.",
  howFound: "How I found this",
  dataAsOf: "Data as of",
  copySources: "Sources",

  // Plain-language steps in "How I found this"
  stepUnderstood: (label: string) => `Read the question as: ${label}`,
  stepMatched: (names: string) => `Matched: ${names}`,
  stepRead: (n: number) => (n === 1 ? "Read 1 collected page" : `Read ${n} collected pages`),
  stepCode: "Built the answer in code from the fact table",
  stepModel: "Wrote the answer from those pages only",
  stepTime: (s: string) => `Took ${s}`,
};

type Dict = typeof en;

const ar: Dict = {
  welcomeHeadline: "إجابات موثّقة بالمصادر عن مشاريع دار جلوبال ومنازل وصلت",
  welcomeHeadlineWasalt: "إجابات موثّقة بالمصادر عن مشاريع ومنازل وصلت في السعودية",
  welcomeChipsLabel: "أسئلة للبدء",
  welcomeChips: [
    "مشاريع في عُمان",
    "أخبرني عن ترامب تاور جدة",
    "قارن بين ترامب تاور جدة ونبتون",
    "دفعة مقدّمة 20% من 2,000,000 ر.س",
  ],
  welcomePhotoCaption: (name: string) => `${name}. الصورة من صفحة المشروع لدى دار جلوبال`,

  composerLabel: "سؤالك",
  send: "إرسال",
  stop: "إيقاف",
  stopLabel: "أوقف الإجابة",
  rateLimited: (s: number) =>
    s >= 90 ? `تمهّل قليلاً، جرّب بعد ${arMinutes(Math.round(s / 60))}.` : `تمهّل قليلاً، جرّب بعد ${arSeconds(s)}.`,
  rateLimitedDone: "يمكنك السؤال الآن.",
  legalLine: "ليست قناة رسمية ولا تقدّم نصيحة.",
  tooLong: "يمكن أن يصل السؤال إلى 1,000 حرف. اختصره لإرساله.",
  charsLeft: (n: number) => `تبقّى ${n} حرف`,
  privacy: "الخصوصية",

  jumpLatest: "انتقل إلى آخر رسالة",

  notAnswered: "لم تتم الإجابة",
  answerReady: "الإجابة جاهزة.",

  actionsLabel: "إجراءات الإجابة",
  copy: "انسخ الإجابة",
  copied: "تم النسخ",
  retry: "اسأل مجدداً",
  helpful: "مفيدة",
  notHelpful: "غير مفيدة",
  feedbackLocal: "شكراً. يبقى تقييمك في هذا المتصفح فقط.",
  howFound: "كيف توصّلت إلى هذه الإجابة؟",
  dataAsOf: "البيانات بتاريخ",
  copySources: "المصادر",

  stepUnderstood: (label: string) => `فهمت السؤال على أنه: ${label}`,
  stepMatched: (names: string) => `المطابقة: ${names}`,
  stepRead: (n: number) =>
    n === 1 ? "قرأت صفحة واحدة من الصفحات المجمّعة" : n === 2 ? "قرأت صفحتين من الصفحات المجمّعة" : n <= 10 ? `قرأت ${n} صفحات من الصفحات المجمّعة` : `قرأت ${n} صفحة من الصفحات المجمّعة`,
  stepCode: "بنيت الإجابة برمجياً من جدول الحقائق",
  stepModel: "كتبت الإجابة من هذه الصفحات وحدها",
  stepTime: (s: string) => `استغرق ذلك ${s}`,
};

export const CONV: Record<Lang, Dict> = { en, ar };
export type ConvStrings = Dict;

/** Latency in plain words: never "0.0 s". */
export function fmtLatency(ms: number, lang: Lang): string {
  const unit = lang === "ar" ? "ثانية" : "s";
  if (!Number.isFinite(ms) || ms < 100) return lang === "ar" ? `أقل من 0.1 ${unit}` : `<0.1 ${unit}`;
  return `${(ms / 1000).toFixed(1)} ${unit}`;
}
