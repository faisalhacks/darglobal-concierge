"use client";
import Link from "next/link";
import { useApp } from "@/components/AppContext";
import { SiteFooter } from "@/components/SiteFooter";
import { Mark, SiteHeader } from "@/components/SiteHeader";

export default function NotFound() {
  const { lang } = useApp();
  const ar = lang === "ar";
  return (
    <div style={{ minHeight: "100dvh", display: "flex", flexDirection: "column" }}>
      <SiteHeader showStatus={false} />
      <main id="main" className="notfound">
        <Mark size={32} />
        <h1>{ar ? "هذه الصفحة غير موجودة" : "This page is not here"}</h1>
        <p>{ar ? "ربما تغيّر الرابط. المحادثة هي نقطة البداية." : "The link may have changed. The conversation is the place to start."}</p>
        <p><Link href="/" className="cta">{ar ? "العودة إلى المساعد" : "Back to the concierge"}</Link></p>
      </main>
      <SiteFooter />
    </div>
  );
}
