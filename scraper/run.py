"""Fetch stage (the ONE fetch lane). Re-runnable: snapshots are reused, never re-fetched.

    python scraper/run.py            # fetch everything in the plan that is not yet snapshotted
    python scraper/run.py --dry      # print the plan only

Order: robots/sitemaps -> static pages -> listing samples (SRP) -> project pages discovered on SRPs.
DarGlobal: blocked by an Imperva/Incapsula bot challenge on 2026-11-19 (see RECON.md); the fetcher
refuses any further DarGlobal request while snapshots/_blocked.json records that.
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import unquote

from fetch import CapReached, Fetcher, SiteBlocked, snap_paths

ROBOTS = [
    "https://www.darglobal.co.uk/robots.txt",
    "https://darglobal.co.uk/sitemap.xml",
    "https://wasalt.sa/robots.txt",
    "https://wasalt.sa/llms.txt",
    "https://auction.wasalt.sa/robots.txt",
    "https://blog.wasalt.sa/robots.txt",
    "https://cdn.wasalt.sa/sitemap/static_sitemap_en_sa.xml.gz",
    "https://cdn.wasalt.sa/sitemap/category_sitemap_en_sa.xml.gz",
]

# DarGlobal coverage plan (all blocked at the moment; kept so a future permitted run is one command)
DARGLOBAL_STATIC = ["https://darglobal.co.uk/about", "https://darglobal.co.uk/partners", "https://darglobal.co.uk/faq",
                    "https://darglobal.co.uk/get-in-touch", "https://darglobal.co.uk/projects"]

WASALT_STATIC = [
    "https://wasalt.sa/en", "https://wasalt.sa/ar",
    "https://wasalt.sa/en/corporate", "https://wasalt.sa/ar/corporate",
    "https://wasalt.sa/en/s/masterplan", "https://wasalt.sa/en/s/wasalt-business",
    "https://wasalt.sa/en/s/terms-of-use", "https://wasalt.sa/en/s/terms-of-advertising",
    "https://wasalt.sa/en/s/terms-n-conditions-for-auction", "https://wasalt.sa/en/s/privacy-policy",
    "https://wasalt.sa/en/wb-daily-rentals",
    "https://auction.wasalt.sa/en",
    "https://blog.wasalt.sa/en/",
]

CITIES = ["riyadh", "jeddah", "makkah", "madinah", "dammam", "al-khobar", "khamis-mushayt", "taif"]
SRP = []
for c in CITIES:
    SRP.append(f"https://wasalt.sa/en/properties-for-sale-in-{c}")
    SRP.append(f"https://wasalt.sa/en/properties-for-rent-in-{c}")
for c in ["riyadh", "jeddah"]:
    for t in ["villas-for-sale", "apartments-for-sale", "apartments-for-rent", "villas-for-rent", "lands-for-sale"]:
        SRP.append(f"https://wasalt.sa/en/{t}-in-{c}")
SRP += ["https://wasalt.sa/en/apartments-for-sale-in-makkah", "https://wasalt.sa/en/villas-for-sale-in-dammam",
        "https://wasalt.sa/en/apartments-for-rent-in-dammam", "https://wasalt.sa/en/villas-for-sale-in-madinah"]
# pass 2: more categories (SRP '?page=N' does not paginate server-side, so breadth comes from categories)
SRP += [f"https://wasalt.sa/en/{t}" for t in [
    "apartments-for-sale-in-madinah", "apartments-for-sale-in-dammam", "apartments-for-sale-in-al-khobar",
    "villas-for-sale-in-makkah", "villas-for-sale-in-al-khobar", "lands-for-sale-in-makkah", "lands-for-sale-in-dammam",
    "floors-for-sale-in-riyadh", "floors-for-sale-in-jeddah", "duplexes-for-sale-in-riyadh",
    "properties-for-sale-in-buraydah", "properties-for-sale-in-abha", "properties-for-sale-in-tabuk",
    "properties-for-sale-in-hail", "properties-for-sale-in-al-ahsa", "properties-for-sale-in-jazan",
    "commercial-properties-for-rent-in-riyadh", "showrooms-for-rent-in-riyadh", "apartments-for-rent-in-makkah",
    "apartments-for-rent-in-madinah"]]

MAX_PROJECTS = 140
MAX_BLOG = 8


def project_links(url: str) -> list[str]:
    body, _ = snap_paths(url)
    if not body.exists():
        return []
    t = body.read_text(encoding="utf-8", errors="ignore")
    out = []
    for m in re.findall(r'/en/project/[^"\\\s<>]+', t):
        out.append("https://wasalt.sa" + m)
    return out


def blog_links() -> list[str]:
    body, _ = snap_paths("https://blog.wasalt.sa/en/")
    if not body.exists():
        return []
    t = body.read_text(encoding="utf-8", errors="ignore")
    links = re.findall(r'href="(https://blog\.wasalt\.(?:sa|com)/en/[a-z0-9\-]+/)"', t)
    seen, out = set(), []
    for l in links:
        if any(x in l for x in ("/category/", "/tag/", "/author/", "/page/", "/feed/", "/wp-json/", "/comments/")):
            continue
        l = l.replace("blog.wasalt.com", "blog.wasalt.sa")
        if l not in seen and l != "https://blog.wasalt.sa/en/":
            seen.add(l)
            out.append(l)
    return out[:MAX_BLOG]


def main(dry: bool = False):
    f = Fetcher()
    stats = {"fetched_or_cached": 0, "skipped_blocked": 0, "errors": []}

    def go(urls):
        for u in urls:
            if dry:
                print("PLAN", u)
                continue
            try:
                m, _ = f.get(u)
                stats["fetched_or_cached"] += 1
                if m["status"] != 200:
                    stats["errors"].append(f"{m['status']} {u}")
            except SiteBlocked as e:
                stats["skipped_blocked"] += 1
            except CapReached as e:
                print("CAP", e)
                raise

    try:
        go(ROBOTS)
        go(DARGLOBAL_STATIC)
        go(WASALT_STATIC)
        go(blog_links())
        go(SRP)
        projs, seen = [], set()
        for u in SRP + WASALT_STATIC:
            for p in project_links(u):
                pid = re.search(r"-(\d+)$", unquote(p))
                k = pid.group(1) if pid else p
                if k not in seen:
                    seen.add(k)
                    projs.append(p)
        print(f"discovered {len(projs)} project links")
        go(projs[:MAX_PROJECTS])
    except CapReached:
        pass
    print(json.dumps(stats, indent=1))
    print("live requests in ledger:", f.live_count())


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
