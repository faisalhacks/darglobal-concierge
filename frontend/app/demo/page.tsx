"use client";
import Link from "next/link";
import { useState } from "react";
import { useApp } from "@/components/AppContext";
import { PageShell } from "@/components/PageShell";
import { Mark } from "@/components/SiteHeader";

/** Generic host page showing how the concierge could be embedded (FF_WIDGET_DEMO). Not a real brand site. */
export default function Demo() {
  const { meta, metaState, lang } = useApp();
  const [open, setOpen] = useState(false);
  const enabled = meta?.flags?.FF_WIDGET_DEMO === true;

  if (metaState === "loading") return <PageShell><p className="muted" role="status">Loading…</p></PageShell>;
  if (!enabled) {
    return (
      <PageShell>
        <h1>Widget demo</h1>
        <div className="empty">
          <h2>This demo is switched off on this deployment</h2>
          <p>The embeddable widget is a feature-flagged experiment and stays off until it passes its checks.</p>
          <Link href="/" className="cta">Back to the concierge</Link>
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div className="demo-host" lang="en" dir="ltr">
        <p className="muted small">Example host page. The concierge runs in an isolated iframe and does not touch this page.</p>
        <h1>A residence on the water</h1>
        <p className="lede">Placeholder copy for a generic property website. Open the concierge from the corner to ask about real, published projects.</p>
      </div>
      <div style={{ position: "fixed", insetInlineEnd: 24, insetBlockEnd: 24, zIndex: 5, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 12 }}>
        {open && (
          <iframe
            title="Property Concierge"
            src={`/?embed=1&lang=${lang}`}
            style={{ width: "min(400px, calc(100vw - 48px))", height: "min(640px, calc(100dvh - 120px))", border: "1px solid var(--border)", borderRadius: 16, background: "var(--bg)" }}
            sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
            referrerPolicy="no-referrer"
          />
        )}
        <button type="button" className="composer__btn" style={{ display: "inline-flex", alignItems: "center", gap: 8, borderRadius: 999, padding: "0 20px", minHeight: 48 }} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <Mark size={16} /> {open ? "Close concierge" : "Ask the concierge"}
        </button>
      </div>
    </PageShell>
  );
}
