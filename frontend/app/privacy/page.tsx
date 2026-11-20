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
        <p className="lede">هذا نموذج تجريبي أعدّه متقدّم للوظيفة، وليس قناة رسمية لدار جلوبال أو وصلت.</p>
        <section>
          <h2>ما الذي يُعالَج</h2>
          <p><strong>أسئلتك تُرسل إلى مزوّدي الذكاء الاصطناعي لتوليد الإجابة.</strong> يُرسل سؤالك وآخر ثماني رسائل من المحادثة، مع المقاطع المسترجعة من البيانات المنشورة، إلى <bdi lang="en">OpenRouter</bdi> (نماذج مجانية)، وعند تعذّره إلى <bdi lang="en">NVIDIA</bdi> كمزوّد احتياطي. قد يسجّل هؤلاء المزوّدون الطلبات وفق سياساتهم الخاصة، ولا نتحكم في ذلك.</p>
          <ul>
            <li>لا يخزّن التطبيق نفسه محادثاتك: لا حفظ لنص الأسئلة أو الأجوبة.</li>
            <li>لا حسابات، ولا ملفات تعريف ارتباط للتتبع، ولا تُخزَّن عناوين <bdi lang="en">IP</bdi>.</li>
            <li>تسجّل سجلات التطبيق بيانات وصفية فقط (المدة، المسار، النية)، وليس نص الرسالة.</li>
            <li>تُحذف أرقام الهاتف وعناوين البريد الإلكتروني من الرسالة قبل إرسالها إلى مزوّد الذكاء الاصطناعي.</li>
            <li>لا تشارك بيانات شخصية في المحادثة (اسمك الكامل أو رقم هويتك أو بيانات مصرفية). الحذف التلقائي يلتقط الأنماط الشائعة فقط وليس مضمونًا.</li>
            <li>تفضيلاتك (اللغة والمظهر وحجم الخط) وتقييماتك للإجابات تبقى في متصفحك وحده.</li>
          </ul>
        </section>
        <section>
          <h2>البيانات</h2>
          {hasDg ? (
            <p>البيانات مأخوذة من صفحات عامة فقط على <bdi lang="en">wasalt.sa</bdi> و <bdi lang="en">darglobal.co.uk</bdi>، مع حذف أي بيانات شخصية. يحجب موقع دار جلوبال العملاء الآليين، فتوقّف الكاشط ولم يُتجاوز أي تحدٍّ: قُرئت 13 صفحة منه عبر متصفح المالك نفسه بوتيرة بشرية، وجاءت بقية معلومات دار جلوبال من مصادر عامة لجهات أخرى (نسخة مرآة لإفصاح في بورصة لندن وتقارير صحفية)، مع بيان أصل كل منها. صور المشاريع تُحمَّل في متصفحك مباشرة من شبكتي صور وصلت (<bdi lang="en">imagedelivery.net</bdi>) ودار جلوبال (<bdi lang="en">cdn.darglobal.co.uk</bdi>) دون إرسال المُحيل، ولا يُعاد استضافتها.</p>
          ) : (
            <p>البيانات مأخوذة من صفحات عامة فقط على <bdi lang="en">wasalt.sa</bdi>، مع حذف أي بيانات شخصية. يحجب موقع <bdi lang="en">darglobal.co.uk</bdi> العملاء الآليين، ولا تتضمن البيانات حالياً أي مشروع لدار جلوبال. صور المشاريع تُحمَّل في متصفحك مباشرة من شبكة صور وصلت (<bdi lang="en">imagedelivery.net</bdi>) دون إرسال المُحيل، ولا يُعاد استضافتها.</p>
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
        <p><strong>Your questions are sent to AI providers to generate the answer.</strong> Your question and up to the last eight messages of the conversation, plus the passages retrieved from the published data, are sent to OpenRouter (free models) and, when OpenRouter is unavailable, to NVIDIA as the backup provider. Those providers may log requests under their own policies; we do not control that.</p>
        <ul>
          <li>The app itself stores no chats: question and answer text is not saved.</li>
          <li>There are no accounts, no tracking cookies and no stored IP addresses.</li>
          <li>The app&apos;s logs hold metadata only (timing, path, intent), never message text.</li>
          <li>Phone numbers and email addresses are stripped from your message before it is sent to an AI provider.</li>
          <li>Please do not share personal details in the chat (full name, ID number, bank details). The automatic stripping catches common patterns only and is not a guarantee.</li>
          <li>Your preferences (language, theme, text size) and any answer ratings stay in your own browser.</li>
        </ul>
      </section>
      <section>
        <h2>Where the data comes from</h2>
        {hasDg ? (
          <p>Only publicly available pages: wasalt.sa, collected at a polite rate, and darglobal.co.uk, which blocks automated clients, so the scraper stopped there and no challenge was bypassed. Thirteen of its pages were read through the owner&apos;s own browser at a human pace; the other DarGlobal facts come from public third-party sources (an LSE filing mirror and press reports), labelled by origin. Personal details such as agent names and phone numbers are removed. Project images load in your browser directly from Wasalt&apos;s image CDN (imagedelivery.net) and DarGlobal&apos;s (cdn.darglobal.co.uk), with no referrer sent; they are not re-hosted.</p>
        ) : (
          <p>Only publicly available pages on wasalt.sa, collected at a polite rate. darglobal.co.uk blocks automated clients, and no DarGlobal project page is in the dataset yet. Personal details such as agent names and phone numbers are removed. Project images load in your browser directly from Wasalt&apos;s image CDN (imagedelivery.net), with no referrer sent; they are not re-hosted.</p>
        )}
        <p>Nothing here is investment advice. Prices and availability change; verify every detail with DarGlobal or Wasalt directly.</p>
      </section>
      {email && (<section><h2>Questions</h2><p>About this prototype: <a href={`mailto:${email}`}>{email}</a></p></section>)}
    </PageShell>
  );
}
