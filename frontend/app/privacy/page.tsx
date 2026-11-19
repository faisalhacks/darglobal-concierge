"use client";
import { useApp } from "@/components/AppContext";
import { PageShell } from "@/components/PageShell";

export default function Privacy() {
  const { lang, meta } = useApp();
  const email = meta?.candidate?.email;
  const hasDg = (meta?.coverage?.DarGlobal?.projects ?? meta?.counts_by_site?.DarGlobal?.projects ?? 0) > 0;
  if (lang === "ar") {
    return (
      <PageShell>
        <h1>الخصوصية</h1>
        <p className="lede">هذا نموذج أولي من مرشّح لوظيفة، وليس قناة رسمية لدار جلوبال أو وصلت.</p>
        <section>
          <h2>ما الذي يُعالَج</h2>
          <ul>
            <li>يُرسل سؤالك وآخر ثماني رسائل من المحادثة إلى الخادم للإجابة، ولا تُحفظ.</li>
            <li>لا توجد حسابات ولا ملفات تعريف ارتباط للتتبع ولا تخزين لعناوين IP.</li>
            <li>تسجّل السجلات بيانات وصفية فقط (المدة، المسار، النية)، وليس نص الرسالة.</li>
            <li>عند توفر النموذج اللغوي، يُرسل السؤال والمقاطع المسترجعة إلى OpenRouter بصفته معالجاً خارجياً لنموذج مجاني.</li>
            <li>تُحفظ تفضيلات اللغة فقط في متصفحك.</li>
          </ul>
        </section>
        <section>
          <h2>البيانات</h2>
          {hasDg ? (
            <p>البيانات مأخوذة من صفحات عامة فقط على wasalt.sa وdarglobal.co.uk، مع حذف أي بيانات شخصية. يحجب موقع دار جلوبال العملاء الآليين، لذا حُفظت صفحاته يدوياً في متصفح عادي صفحةً صفحة. صور المشاريع تُحمَّل في متصفحك مباشرة من شبكتي صور وصلت (imagedelivery.net) ودار جلوبال (cdn.darglobal.co.uk) دون إرسال المُحيل، ولا يُعاد استضافتها.</p>
          ) : (
            <p>البيانات مأخوذة من صفحات عامة فقط على wasalt.sa، مع حذف أي بيانات شخصية. يحجب موقع darglobal.co.uk العملاء الآليين، ولا تتضمن البيانات حالياً أي مشروع لدار جلوبال. صور المشاريع تُحمَّل في متصفحك مباشرة من شبكة صور وصلت (imagedelivery.net) دون إرسال المُحيل، ولا يُعاد استضافتها.</p>
          )}
          <p>ليست نصيحة استثمارية. تحقّق من كل التفاصيل مع الجهة الرسمية.</p>
        </section>
        {email && (<section><h2>التواصل</h2><p>للأسئلة حول هذا النموذج: <a href={`mailto:${email}`} dir="ltr">{email}</a></p></section>)}
      </PageShell>
    );
  }
  return (
    <PageShell>
      <h1>Privacy</h1>
      <p className="lede">This is a candidate&apos;s prototype for a job application. It is not an official DarGlobal or Wasalt channel.</p>
      <section>
        <h2>What is processed</h2>
        <ul>
          <li>Your question and up to the last eight messages of the conversation are sent to the server to produce an answer. They are not stored.</li>
          <li>There are no accounts, no tracking cookies and no stored IP addresses.</li>
          <li>Logs hold metadata only (timing, path, intent), never message text.</li>
          <li>When the language model is available, the question and the retrieved passages are sent to OpenRouter, acting as a third-party processor for a free model. Some free model endpoints may log prompts under their own terms; the model in use is listed on the How it works page.</li>
          <li>Only your language preference is kept, in your own browser.</li>
        </ul>
      </section>
      <section>
        <h2>Where the data comes from</h2>
        {hasDg ? (
          <p>Only publicly available pages: wasalt.sa, collected at a polite rate, and darglobal.co.uk, which blocks automated clients, so its pages were saved by hand in an ordinary browser, one at a time. Personal details such as agent names and phone numbers are removed. Project images load in your browser directly from Wasalt&apos;s image CDN (imagedelivery.net) and DarGlobal&apos;s (cdn.darglobal.co.uk), with no referrer sent; they are not re-hosted.</p>
        ) : (
          <p>Only publicly available pages on wasalt.sa, collected at a polite rate. darglobal.co.uk blocks automated clients, and no DarGlobal project page is in the dataset yet. Personal details such as agent names and phone numbers are removed. Project images load in your browser directly from Wasalt&apos;s image CDN (imagedelivery.net), with no referrer sent; they are not re-hosted.</p>
        )}
        <p>Nothing here is investment advice. Prices and availability change; verify every detail with DarGlobal or Wasalt directly.</p>
      </section>
      {email && (<section><h2>Questions</h2><p>About this prototype: <a href={`mailto:${email}`}>{email}</a></p></section>)}
    </PageShell>
  );
}
