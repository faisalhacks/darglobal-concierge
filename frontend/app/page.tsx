"use client";
import { useEffect, useState } from "react";
import { Chat } from "@/components/Chat";
import { Rail } from "@/components/Rail";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export default function Home() {
  const [embed, setEmbed] = useState(false);
  useEffect(() => {
    try { setEmbed(new URLSearchParams(window.location.search).get("embed") === "1"); } catch { /* ignore */ }
  }, []);
  if (embed) return <div className="embed-shell"><Chat embedded /></div>;
  return (
    <div className="app-shell">
      <SiteHeader />
      <div className="home">
        <Rail />
        <Chat />
      </div>
      <SiteFooter compact />
    </div>
  );
}
