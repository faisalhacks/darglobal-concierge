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
import { AppProvider } from "@/components/AppContext";

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
  twitter: { card: "summary_large_image", title: "Property Concierge", description, images: ["/og.png"] },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0E0E0E" },
    { media: "(prefers-color-scheme: light)", color: "#FAF8F4" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr">
      <body>
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  );
}
