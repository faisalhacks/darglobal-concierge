import type { Metadata, Viewport } from "next";
import "@fontsource/cormorant-garamond/500.css";
import "@fontsource/cormorant-garamond/600.css";
import "@fontsource/hanken-grotesk/400.css";
import "@fontsource/hanken-grotesk/500.css";
import "@fontsource/hanken-grotesk/600.css";
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/500.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import "./globals.css";
import "./shell.css";
import { AppProvider } from "@/components/AppContext";
import { PREPAINT, THEME_COLOR } from "@/lib/prefs";

const description =
  "A candidate prototype concierge that answers questions about DarGlobal projects and Wasalt homes from public pages, with sources. Not an official channel.";

// APP_URL (build-time) makes the Open Graph image URL absolute for link previews.
const APP_URL = process.env.APP_URL || process.env.NEXT_PUBLIC_APP_URL || "http://localhost:7860";

export const metadata: Metadata = {
  metadataBase: new URL(APP_URL),
  title: { default: "Property Concierge · DarGlobal · Wasalt", template: "%s · Property Concierge" },
  description,
  robots: { index: false, follow: false, nocache: true, googleBot: { index: false, follow: false } },
  icons: { icon: [{ url: "/favicon.svg", type: "image/svg+xml" }] },
  openGraph: {
    title: "Property Concierge · DarGlobal · Wasalt",
    description,
    type: "website",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "Property Concierge, a candidate prototype" }],
  },
  other: { google: "notranslate" },
  twitter: { card: "summary_large_image", title: "Property Concierge", description, images: ["/og.png"] },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: THEME_COLOR.dark },
    { media: "(prefers-color-scheme: light)", color: THEME_COLOR.light },
  ],
};

// translate="no": the interface has its own language toggle (the one source of truth for lang/dir). Browser
// auto-translate rewrote the Arabic shell into English inside an RTL layout and changed text lengths mid-stream.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" translate="no" suppressHydrationWarning>
      <head>
        {/* Before first paint: language (?lang= / toggle / storage / browser), theme (data-theme), text size
            (--text-scale), rail split (--rail-w, data-rail) and theme-color, all from storage inside try/catch. So the
            first frame already has the stored theme and split: no flash, no layout shift. Hydration ignores these
            <html> attributes (suppressHydrationWarning). The page stays hidden (AppProvider, at most 1.5 s) until
            /api/meta is known. */}
        <script dangerouslySetInnerHTML={{ __html: PREPAINT }} />
      </head>
      <body>
        <noscript><style>{".app-root{visibility:visible!important}"}</style></noscript>
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
