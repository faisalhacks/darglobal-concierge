// Mirrors the binding API/SSE contract. Do not change without DECISIONS.md.
export type Site = "DarGlobal" | "Wasalt";
export type Lang = "en" | "ar";
export interface Money { amount: number; currency: string }
export interface Source { site: string; title: string; url: string; scraped_at: string; brand?: Site }
export interface ProjectCard {
  id: string; slug: string; name: string; site: Site; city: string; country: string;
  price_from: Money | null; status: string | null; image_url: string | null; source_url: string;
  /** C2: "page" = a collected project page, "index" = only listed on the DarGlobal projects index. */
  detail?: "page" | "index" | "thirdparty";
  /** Who published source_url: "DarGlobal", "Wasalt", or an honest third-party label such as "LSE filing via ticker.app". */
  source_site?: string;
  /** Localised place names for display; city/country stay the raw dataset values. */
  city_display?: string | null; country_display?: string | null;
  /** C2: localised label, e.g. "Price on request" when no price is published. */
  price_label?: string | null;
}
export interface ListingCard {
  id: string; title: string; site: Site; listing_type: "buy" | "rent"; price: Money | null;
  beds: number | null; baths: number | null; area_m2: number | null; district: string | null;
  city: string | null; image_url: string | null; source_url: string; city_display?: string | null;
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
  retrieved: { id: string; score: number; title?: string; site?: string; section?: string }[]; llm_calls: number; model: string | null;
  latency_ms: number; cache_hit: boolean; degraded: boolean;
  fallback_hops?: number;
  degraded_reason?: DegradedReason | null;
}
export type DegradedReason = "rate_limited" | "quota" | "timeout" | "all_models_down" | "maintenance" | "no_model";
export type LlmState = "ok" | "quota" | "cooling" | "off" | "maintenance";
export interface LlmMeta {
  mode: "live" | "mock" | "off"; state: LlmState;
  budget?: { used: number; cap: number };
  pool?: { model: string; state: "healthy" | "cooling" | "removed" }[];
}
export interface Coverage {
  DarGlobal?: { projects: number; detail_pages: number; prices_published: boolean };
  Wasalt?: { projects: number; listings: number };
}
export type ErrorCode = "RATE_LIMITED" | "MODEL_UNAVAILABLE" | "BAD_INPUT" | "INTERNAL";
export interface ErrorEvent { code: ErrorCode; message: string; retry_after_s?: number }

export interface ApiMeta {
  dataset_version: string; data_as_of: string;
  counts: { projects: number; listings: number; pages: number; chunks: number };
  counts_by_site?: Record<string, { projects: number; listings: number }>;
  completeness: Record<string, number>; models: string[]; llm_available: boolean;
  flags: Record<string, boolean>;
  candidate: { name: string | null; github: string | null; linkedin: string | null; email: string | null };
  coverage?: Coverage;
  llm?: LlmMeta;
  starter_chips?: { en: string[]; ar: string[] };
}
export interface HistoryItem { role: "user" | "assistant"; content: string }
