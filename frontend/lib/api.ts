import type { ApiMeta } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { signal, headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json() as Promise<T>;
}

export const getMeta = (signal?: AbortSignal) => getJSON<ApiMeta>("/api/meta", signal);

/** Only official domains become clickable links (SPEC §18). */
const ALLOWED = ["darglobal.co.uk", "darglobal.com", "wasalt.sa", "wasalt.com"];
export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" && u.protocol !== "http:") return null;
    const h = u.hostname.toLowerCase();
    return ALLOWED.some((d) => h === d || h.endsWith(`.${d}`)) ? u.toString() : null;
  } catch { return null; }
}
export function safeImage(url: string | null | undefined): string | null {
  if (!url) return null;
  try { const u = new URL(url); return u.protocol === "https:" ? u.toString() : null; } catch { return null; }
}
