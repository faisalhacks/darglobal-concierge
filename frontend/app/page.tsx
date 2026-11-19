"use client";
import { useEffect, useRef, useState } from "react";
import { useApp, useRail } from "@/components/AppContext";
import { Chat } from "@/components/Chat";
import { Rail } from "@/components/Rail";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import { Splitter } from "@/components/Splitter";

/** Watches the chat for an active conversation (it marks its root .chat--active), without reaching into the chat. */
function useConversationActive(root: React.RefObject<HTMLElement | null>) {
  const [active, setActive] = useState(false);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const check = () => setActive(Boolean(el.querySelector(".chat--active")));
    check();
    const mo = new MutationObserver(check);
    mo.observe(el, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, [root]);
  return active;
}

function Home() {
  const { resetChat } = useApp();
  const rail = useRail();
  const home = useRef<HTMLDivElement | null>(null);
  const convo = useConversationActive(home);
  const answered = useRef(false);

  useEffect(() => { rail.setPresent(true); return () => rail.setPresent(false); }, [rail.setPresent]); // eslint-disable-line react-hooks/exhaustive-deps

  // The chat offers "New conversation" once a turn exists and nothing is in flight: that is the first answer.
  useEffect(() => {
    if (resetChat && convo && !answered.current) { answered.current = true; rail.onFirstAnswer(); }
  }, [resetChat, convo]); // eslint-disable-line react-hooks/exhaustive-deps
  // Short landscape screens (max-height 500px): the header is not sticky. Once a conversation starts, the document
  // scrolls by the header's height so the thread and composer get the whole viewport (chrome budget, spec 1).
  useEffect(() => {
    if (!convo) return;
    let mq: MediaQueryList | null = null;
    try { mq = window.matchMedia("(max-height: 500px)"); } catch { return; }
    const apply = () => {
      if (!mq?.matches) return;
      const h = document.querySelector<HTMLElement>(".site-header")?.offsetHeight ?? 0;
      window.scrollTo({ top: h, behavior: "auto" });
    };
    apply();
    mq.addEventListener?.("change", apply);
    return () => mq?.removeEventListener?.("change", apply);
  }, [convo]);
  useEffect(() => {
    if (!convo && answered.current) { answered.current = false; rail.onConversationCleared(); }
  }, [convo]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="app-shell" data-convo={convo ? "1" : undefined}>
      <SiteHeader />
      <div className="home" ref={home}>
        <Rail />
        <Splitter />
        <Chat />
      </div>
      <SiteFooter compact />
    </div>
  );
}

export default function Page() {
  const [embed, setEmbed] = useState(false);
  useEffect(() => {
    try { setEmbed(new URLSearchParams(window.location.search).get("embed") === "1"); } catch { /* ignore */ }
  }, []);
  if (embed) return <div className="embed-shell"><Chat embedded /></div>;
  return <Home />;
}
