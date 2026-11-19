"use client";
import { useEffect, useState } from "react";
import { getJSON } from "@/lib/api";

/** Published fields a card or compare header may need, read once per project from /api/projects/{slug}. Only what the
 * record holds is returned; nothing is composed here. */
export interface ProjectDetail {
  unit_types: string[]; property_types: string[];
  area_min_m2: number | null; area_max_m2: number | null; handover_year: string | null;
  brand_partner: string | null; scraped_at: string | null; image_urls: string[];
  licence_note: string | null; licence_url: string | null;
}

const list = (v: unknown): string[] => {
  if (Array.isArray(v)) return v.map(String).filter((x) => x.trim());
  if (typeof v === "string" && v.trim()) {
    try { const j = JSON.parse(v); if (Array.isArray(j)) return j.map(String).filter((x) => x.trim()); } catch { /* plain text */ }
    return [v.trim()];
  }
  return [];
};
const num = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() ? Number(v) : NaN;
  return Number.isFinite(n) && n > 0 ? n : null;
};
const str = (v: unknown): string | null => (v == null || v === "" ? null : String(v));

export function parseDetail(d: Record<string, unknown>): ProjectDetail {
  return {
    unit_types: list(d.unit_types), property_types: list(d.property_types),
    area_min_m2: num(d.area_min_m2), area_max_m2: num(d.area_max_m2),
    handover_year: str(d.handover_year)?.replace(/\.0$/, "") ?? null,
    brand_partner: str(d.brand_partner), scraped_at: str(d.scraped_at), image_urls: list(d.image_urls),
    licence_note: str(d.licence_note ?? d.license_note), licence_url: str(d.licence_url ?? d.license_url),
  };
}

const cache = new Map<string, Promise<ProjectDetail | null>>();
export function fetchProjectDetail(slug: string): Promise<ProjectDetail | null> {
  let pr = cache.get(slug);
  if (!pr) {
    pr = getJSON<Record<string, unknown>>(`/api/projects/${encodeURIComponent(slug)}`).then(parseDetail).catch(() => null);
    cache.set(slug, pr);
  }
  return pr;
}

/** The record's detail, or null while loading / when the request fails (the card then shows what it already has). */
export function useProjectDetail(slug: string | null | undefined, skip = false): ProjectDetail | null {
  const [d, setD] = useState<ProjectDetail | null>(null);
  useEffect(() => {
    if (!slug || skip) return;
    let live = true;
    fetchProjectDetail(slug).then((x) => { if (live) setD(x); });
    return () => { live = false; };
  }, [slug, skip]);
  return d;
}

/** Details for several projects at once (shared cache), in input order; entries stay null until they arrive. */
export function useProjectDetails(slugs: string[]): (ProjectDetail | null)[] {
  const key = slugs.join("|");
  const [list, setList] = useState<(ProjectDetail | null)[]>([]);
  useEffect(() => {
    if (!key) { setList([]); return; }
    let live = true;
    Promise.all(key.split("|").map(fetchProjectDetail)).then((xs) => { if (live) setList(xs); });
    return () => { live = false; };
  }, [key]);
  return list;
}
