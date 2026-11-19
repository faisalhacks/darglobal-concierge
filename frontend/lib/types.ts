// Mirrors the binding API/SSE contract. Do not change without DECISIONS.md.
export type Site = "DarGlobal" | "Wasalt";
export type Lang = "en" | "ar";
export interface Money { amount: number; currency: string }
export interface Source {
  site: string; title: string; url: string; scraped_at: string; brand?: Site;
  /** Backend citation number: a [n] marker in the prose names the source whose n matches (else position n-1). */
  n?: number;
}
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
  /** Optional published facts. When absent on the card they are read once from /api/projects/{slug}. */
  unit_types?: string[] | string | null; property_types?: string[] | string | null;
  area_min_m2?: number | null; area_max_m2?: number | null; handover_year?: number | string | null;
  brand_partner?: string | null; scraped_at?: string | null; image_urls?: string[] | null;
}
export interface ListingCard {
  id: string; title: string; site: Site; listing_type: "buy" | "rent"; price: Money | null;
  beds: number | null; baths: number | null; area_m2: number | null; district: string | null;
  city: string | null; image_url: string | null; source_url: string; city_display?: string | null;
  scraped_at?: string | null;
  /** Lane E: set when area per bedroom is outside a plausible range; the card then hedges the area. */
  area_flag?: boolean | string | null;
  /** Optional: price in whole USD via the official peg (pegged currencies only). The card shows "≈ $X" only if set. */
  price_usd_approx?: number | null;
}
export interface MetaEvent { request_id: string; lang: Lang; intent: string; dataset_version: string; data_as_of: string }
export interface CardsEvent {
  projects: ProjectCard[]; listings: ListingCard[];
  /** Lane E (optional): projects only listed on the index, sent apart from `projects`; and the total the prose states. */
  index_only?: ProjectCard[]; total?: number;
  footnotes?: Footnote[];
}
/** A licence or legal line shown under the rich block, never inside a card. */
export type Footnote = string | { text: string; url?: string | null; lang?: Lang | null };
export interface CompareEvent {
  columns: { id: string; name: string; site: Site; image_url?: string | null; slug?: string | null }[];
  /** `differs` (lane E) is computed in code from the row values; the UI computes the same when it is absent. */
  rows: { label: string; values: (string | null)[]; differs?: boolean }[];
  sources: Source[];
  /** One code-built verdict line from the table values only. */
  verdict?: string | null;
  footnotes?: Footnote[];
}
/** Advisor / sales / viewing intent: official links only; nothing is sent or stored. */
export interface HandoffEvent {
  project?: string | null;
  links?: { site: string; title?: string | null; url: string }[];
}
/** Off-topic or refusal pivot: one real project from the corpus. */
export interface SpotlightEvent { project: ProjectCard }
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
  provider?: "openrouter" | "nvidia-backup" | null;
  degraded_reason?: DegradedReason | null;
}
export type DegradedReason = "rate_limited" | "quota" | "timeout" | "all_models_down" | "maintenance" | "no_model";
export type LlmState = "ok" | "quota" | "cooling" | "off" | "maintenance";
export interface LlmMeta {
  mode: "live" | "mock" | "off"; state: LlmState;
  budget?: { used: number; cap: number };
  pool?: { model: string; state: "healthy" | "cooling" | "removed" }[];
  backup?: { enabled: boolean; provider: "nvidia" | null; model: string | null; used: number; cap: number };
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
