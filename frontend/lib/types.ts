// Mirrors the binding API/SSE contract. Do not change without DECISIONS.md.
export type Site = "DarGlobal" | "Wasalt";
export type Lang = "en" | "ar";
export interface Money { amount: number; currency: string }
export interface Source { site: Site; title: string; url: string; scraped_at: string }
export interface ProjectCard {
  id: string; slug: string; name: string; site: Site; city: string; country: string;
  price_from: Money | null; status: string | null; image_url: string | null; source_url: string;
}
export interface ListingCard {
  id: string; title: string; site: Site; listing_type: "buy" | "rent"; price: Money | null;
  beds: number | null; baths: number | null; area_m2: number | null; district: string | null;
  city: string | null; image_url: string | null; source_url: string;
}
export interface MetaEvent { request_id: string; lang: Lang; intent: string; dataset_version: string; data_as_of: string }
export interface CardsEvent { projects: ProjectCard[]; listings: ListingCard[] }
export interface CompareEvent {
  columns: { id: string; name: string; site: Site }[];
  rows: { label: string; values: (string | null)[] }[];
  sources: Source[];
}
export interface CalcEvent {
  kind: "price_per_m2" | "down_payment" | "installment_split" | "currency_convert";
  inputs: Record<string, unknown>; result: Record<string, unknown>; formula: string; disclaimer: string;
}
export interface Chip { label: string; message: string }
export interface TraceEvent {
  intent: string; path: "code" | "llm_tool" | "template"; tool: string | null;
  retrieved: { id: string; score: number }[]; llm_calls: number; model: string | null;
  latency_ms: number; cache_hit: boolean; degraded: boolean;
}
export type ErrorCode = "RATE_LIMITED" | "MODEL_UNAVAILABLE" | "BAD_INPUT" | "INTERNAL";
export interface ErrorEvent { code: ErrorCode; message: string; retry_after_s?: number }

export interface ApiMeta {
  dataset_version: string; data_as_of: string;
  counts: { projects: number; listings: number; pages: number; chunks: number };
  completeness: Record<string, number>; models: string[]; llm_available: boolean;
  flags: Record<string, boolean>;
  candidate: { name: string | null; github: string | null; linkedin: string | null; email: string | null };
}
export interface HistoryItem { role: "user" | "assistant"; content: string }
