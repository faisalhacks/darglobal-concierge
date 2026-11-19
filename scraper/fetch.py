"""Single fetch lane for the whole project.

Rules enforced here (SPEC 6.3):
- strictly sequential, one request at a time across ALL sites
- >= 2 s between any two requests (or the site's crawl-delay if higher)
- honest User-Agent, no email, no cookies forged, no proxies
- stop a site permanently on 403 / 429 / CAPTCHA markers
- every raw response saved under scraper/snapshots/ ; cached responses are never re-fetched
- hard cap on total live requests (persisted in snapshots/_ledger.jsonl)
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

UA = "DarGlobalConciergeCandidatePrototype/1.0 (job-assessment prototype; non-commercial)"
ROOT = Path(__file__).resolve().parent
SNAP = ROOT / "snapshots"
SNAP.mkdir(exist_ok=True)
LEDGER = SNAP / "_ledger.jsonl"
BLOCKED = SNAP / "_blocked.json"
HARD_CAP = 450
MIN_DELAY = 2.0
CAPTCHA_MARKERS = ("_Incapsula_Resource", "Incapsula incident", "g-recaptcha", "hcaptcha", "cf-challenge", "challenge-platform/h/", "Attention Required! | Cloudflare",
                   "captcha-delivery", "px-captcha", "Just a moment...")


class SiteBlocked(Exception):
    pass


class CapReached(Exception):
    pass


def key_for(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:20]


def snap_paths(url: str):
    host = urlparse(url).netloc.replace(":", "_")
    d = SNAP / host
    d.mkdir(exist_ok=True)
    k = key_for(url)
    return d / f"{k}.body", d / f"{k}.meta.json"


class Fetcher:
    def __init__(self, crawl_delays: dict[str, float] | None = None):
        self.crawl_delays = crawl_delays or {}
        self.client = httpx.Client(headers={"User-Agent": UA, "Accept-Language": "en,ar;q=0.8"},
                                   follow_redirects=False, timeout=30.0)
        self.last = 0.0
        self.blocked = json.loads(BLOCKED.read_text()) if BLOCKED.exists() else {}

    def live_count(self) -> int:
        if not LEDGER.exists():
            return 0
        return sum(1 for _ in LEDGER.open(encoding="utf-8"))

    def cached(self, url: str):
        body, meta = snap_paths(url)
        if meta.exists() and body.exists():
            return json.loads(meta.read_text(encoding="utf-8")), body.read_bytes()
        return None

    def get(self, url: str, force: bool = False):
        """Return (meta, bytes). Uses snapshot if present."""
        if not force:
            c = self.cached(url)
            if c:
                return c
        host = urlparse(url).netloc
        base = host.removeprefix("www.")
        if base in self.blocked:
            raise SiteBlocked(f"{base} blocked earlier: {self.blocked[base]}")
        if self.live_count() >= HARD_CAP:
            raise CapReached(f"hard cap {HARD_CAP} reached")
        delay = max(MIN_DELAY, self.crawl_delays.get(base, 0))
        wait = self.last + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        t0 = time.monotonic()
        err = None
        cur, hops = url, 0
        while True:
            try:
                r = self.client.get(cur)
                status, content, ctype, final = r.status_code, r.content, r.headers.get("content-type", ""), str(r.url)
            except httpx.HTTPError as e:
                status, content, ctype, final, err = 0, b"", "", cur, repr(e)
                break
            self.last = time.monotonic()
            if r.is_redirect and hops < 4:
                nxt = str(r.next_request.url) if r.next_request else None
                with LEDGER.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"url": cur, "status": status, "redirect_to": nxt,
                                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
                # never follow into internal search results (robots.txt + llms.txt) or another host's challenge
                if not nxt or "/search" in urlparse(nxt).path or self.live_count() >= HARD_CAP:
                    final, content, ctype = nxt or cur, b"", "redirect"
                    break
                cur, hops = nxt, hops + 1
                time.sleep(max(0.0, self.last + delay - time.monotonic()))
                continue
            break
        self.last = time.monotonic()
        meta = {"url": url, "final_url": final, "status": status, "content_type": ctype,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "elapsed_ms": int((self.last - t0) * 1000), "bytes": len(content), "error": err}
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"url": url, "status": status, "at": meta["fetched_at"]}) + "\n")
        text_head = content[:200000].decode("utf-8", "ignore")
        reason = None
        if status in (403, 429):
            reason = f"HTTP {status} on {url}"
        elif status == 200 and "html" in ctype and any(m in text_head for m in CAPTCHA_MARKERS) and len(content) < 60000:
            reason = f"CAPTCHA/challenge marker on {url}"
        body_p, meta_p = snap_paths(url)
        if status != 0:
            body_p.write_bytes(content)
            meta_p.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        print(f"[{self.live_count():3d}] {status} {len(content):>8}B {url}", flush=True)
        if reason:
            self.blocked[base] = reason
            BLOCKED.write_text(json.dumps(self.blocked, indent=1))
            raise SiteBlocked(reason)
        return meta, content
