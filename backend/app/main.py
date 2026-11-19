"""FastAPI entry point. Run: uvicorn backend.app.main:app --port 7860 --no-access-log

Serves /api/* and the static Next.js export (STATIC_DIR) at /. Built for a Hugging Face Docker Space
(port 7860, non-root uid 1000); the same image runs on Render.
"""
from __future__ import annotations

import asyncio

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import Counter, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import calculator, templates
from .arabic import detect_lang
from .planner import place_display
from .chat import ChatRequest, Engine
from .config import FLAG_NAMES, Settings, load_settings
from .backup_provider import wrap_with_backup  # BACKUP-PROVIDER HOOK
from .llm import MockLLM, OpenRouterClient
from .retrieval import Retriever
from .store import Store, compare_payload, detail_level, listing_card, project_card

log = logging.getLogger("concierge")

SPA_ROUTES = ("/", "/how-it-works", "/evals", "/privacy", "/demo")
def _flat_completeness(c: dict, prefix: str = "") -> dict:
    """Contract: completeness is {field: ratio}. The dataset stores it per table; flatten to 'table.field'."""
    out: dict = {}
    for k, v in (c or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flat_completeness(v, key + "."))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = float(v)
    return out


# HF Spaces sets SPACE_HOST (e.g. user-space.hf.space) at runtime; frame only that host, not every *.hf.space.
_FRAME_HOST = (f"https://{os.environ['SPACE_HOST'].strip()}" if os.environ.get("SPACE_HOST", "").strip()
               else "https://*.hf.space")
CSP = ("default-src 'self'; img-src 'self' https://imagedelivery.net https://*.wasalt.sa https://*.wasalt.com "
       "https://*.darglobal.co.uk data:; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; "
       "connect-src 'self'; frame-ancestors 'self' https://huggingface.co " + _FRAME_HOST + "; "
       "base-uri 'self'; form-action 'self'; object-src 'none'")


class RateLimiter:
    """Per-client sliding window, in memory. The client IP is never logged or stored: it is reduced to an
    HMAC with a random per-process key, and only that opaque digest is kept, for at most one window."""

    def __init__(self, n: int, window_s: int):
        self.n, self.w = n, window_s
        self._key = secrets.token_bytes(32)
        self._hits: dict[str, deque] = {}

    def _id(self, ip: str) -> str:
        return hmac.new(self._key, ip.encode(), hashlib.sha256).hexdigest()[:24]

    def check(self, ip: str) -> tuple[bool, int]:
        now = time.monotonic()
        k = self._id(ip)
        q = self._hits.setdefault(k, deque())
        while q and now - q[0] > self.w:
            q.popleft()
        if len(q) >= self.n:
            return False, max(1, int(self.w - (now - q[0])) + 1)
        q.append(now)
        if len(self._hits) > 10_000:  # bound memory
            for kk in [kk for kk, v in self._hits.items() if not v or now - v[-1] > self.w]:
                self._hits.pop(kk, None)
        return True, 0


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=(self)")
        return resp


class GlobalBudget:
    """Process-wide cap on chat requests per minute while an LLM is configured. It does not depend on client
    identity, so it still bounds LLM spend if a client manages to rotate its apparent address."""

    def __init__(self, per_minute: int):
        self.n = per_minute
        self._q: deque = deque()

    def check(self) -> tuple[bool, int]:
        if self.n <= 0:
            return True, 0
        now = time.monotonic()
        while self._q and now - self._q[0] > 60:
            self._q.popleft()
        if len(self._q) >= self.n:
            return False, max(1, int(60 - (now - self._q[0])) + 1)
        self._q.append(now)
        return True, 0


class _TooLarge(Exception):
    pass


class BodyLimit:
    """Pure ASGI middleware. Rejects bodies over max_bytes whether or not Content-Length is sent: the body is
    counted while it streams (chunked uploads included), so an oversized request is never buffered whole."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers") or []:
            if k == b"content-length" and (not v.isdigit() or int(v) > self.max):
                return await self._reject(send)
        seen = 0
        started = False

        async def limited_receive():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body") or b"")
                if seen > self.max:
                    raise _TooLarge()
            return msg

        async def tracking_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    @staticmethod
    async def _reject(send):
        body = json.dumps({"code": "BAD_INPUT", "message": "Request too large."}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})


def _client_ip(request: Request, trusted_hops: int = 0) -> str:
    """Client address for rate limiting.

    The left-most X-Forwarded-For hop is written by the client and can be anything, so it is never used.
    With trusted_hops=N (N proxies we control, e.g. 1 for the HF Spaces / Render edge) the address is the N-th
    hop from the right, i.e. the one our own edge proxy appended. With 0 the header is ignored entirely."""
    if trusted_hops > 0:
        hops = [h.strip() for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
        if len(hops) >= trusted_hops:
            return hops[-trusted_hops]
    return request.client.host if request.client else "unknown"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def starter_chips(store: Store) -> dict:
    """Contract C2: five starter questions per language, built only from rows that exist: a DarGlobal country, a
    DarGlobal project with a collected detail page, a Wasalt search, a calculation, and the trap chip last."""
    dg = [p for p in store.projects if p["site"] == "DarGlobal"] or list(store.projects)
    en, ar = [], []
    countries = Counter(p.get("country") for p in dg if p.get("country"))
    if countries:
        c = countries.most_common(1)[0][0]
        en.append(f"What projects do you have in {c}?")
        ar.append(f"ما المشاريع المتوفرة لديكم في {place_display(c, 'ar')}؟")
    detail = next((p for p in dg if detail_level(p) == "page" and p.get("name_en")), None)
    if detail:
        en.append(f"Tell me about {detail['name_en']}")
        ar.append(f"أخبرني عن {detail.get('name_ar') or detail['name_en']}")
    rent = Counter(x.get("city") for x in store.listings if x.get("city") and x.get("listing_type") == "rent")
    buy = Counter(x.get("city") for x in store.listings if x.get("city") and x.get("listing_type") == "buy")
    if rent:
        city = rent.most_common(1)[0][0]
        en.append(f"Apartments for rent in {city}")
        ar.append(f"شقق للإيجار في {place_display(city, 'ar')}")
    elif buy:
        city = buy.most_common(1)[0][0]
        en.append(f"Properties to buy in {city}")
        ar.append(f"عقارات للبيع في {place_display(city, 'ar')}")
    en.append("20% down on 2,000,000 SAR")
    ar.append("دفعة مقدمة 20% على 2,000,000 ريال")
    fill_en = [m for _, m in templates.DEFAULT_CHIPS["en"][:4]]
    fill_ar = [m for _, m in templates.DEFAULT_CHIPS["ar"][:4]]
    for lst, fill in ((en, fill_en), (ar, fill_ar)):
        for m in fill:
            if len(lst) >= 4:
                break
            if m not in lst:
                lst.append(m)
    en.append(templates.DEFAULT_CHIPS["en"][4][1])
    ar.append(templates.DEFAULT_CHIPS["ar"][4][1])
    return {"en": en[:5], "ar": ar[:5]}


def _make_llm(s: Settings):
    if s.llm_mode == "mock":
        return MockLLM(fail_with=os.environ.get("MOCK_LLM_FAIL") or None)
    if s.llm_available:
        # BACKUP-PROVIDER HOOK: no-op unless BACKUP_PROVIDER=nvidia (+ NVIDIA_API_KEY)
        return wrap_with_backup(OpenRouterClient(s), first_token_s=s.llm_first_token_timeout_s,
                                total_s=s.llm_total_timeout_s)
    return None


async def _refresh_models(llm_obj, every_s: float):
    """Model health without spending quota: re-read the public GET /models list (not a completion) every
    `every_s` seconds and drop pool members that disappeared. No warm-up completions are ever sent."""
    while True:
        await asyncio.sleep(every_s)
        try:
            await llm_obj.check_models()
        except Exception as e:  # noqa: BLE001 - a background refresh must never take the app down
            log.warning("model list refresh failed: %s", type(e).__name__)


def create_app(settings: Settings | None = None, llm=None, embedder=None) -> FastAPI:
    s = settings or load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("uvicorn.access").disabled = True  # access logs contain client IPs

    store = Store.load(s.data_path)
    retriever = Retriever(store, s.index_dir, s.embeddings, s.embed_cache_dir, s.retrieval_threshold,
                          embedder=embedder)
    engine = Engine(s, store, retriever, llm if llm is not None else _make_llm(s))
    limiter = RateLimiter(s.rate_limit_n, s.rate_limit_window_s)
    budget = GlobalBudget(s.global_llm_per_min)

    @asynccontextmanager
    async def lifespan(_app):
        retriever.warm()  # one embed() so the first question does not pay the ONNX warm-up
        llm_obj = engine.llm
        # Layer 1: drop models that are gone / no longer free. GET /models is not a completion: no quota is spent.
        if s.llm_mode not in ("mock", "off") and s.llm_boot_model_check and hasattr(llm_obj, "check_models"):
            try:
                await llm_obj.check_models()
            except Exception as e:  # noqa: BLE001 - boot must never fail on this
                log.warning("model list check failed: %s", type(e).__name__)
        refresher = None
        if s.llm_mode not in ("mock", "off") and s.llm_model_refresh_s > 0 and hasattr(llm_obj, "check_models"):
            refresher = asyncio.create_task(_refresh_models(llm_obj, s.llm_model_refresh_s))
        # ECB reference rates (EUR, GBP, INR): fetched in the background, never awaited by a request.
        fx_task = asyncio.create_task(calculator.fx_refresh_loop()) if os.environ.get("FX_FETCH", "on").lower() not in (
            "off", "0", "false", "no") else None
        yield
        if refresher:
            refresher.cancel()
        if fx_task:
            fx_task.cancel()

    app = FastAPI(title="Property Concierge (candidate prototype)", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.settings, app.state.store, app.state.engine, app.state.retriever = s, store, engine, retriever
    app.state.limiter = limiter
    app.add_middleware(BodyLimit, max_bytes=s.max_body_bytes)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], allow_credentials=False, max_age=600)

    # ------------------------------------------------------------------ chat
    @app.post("/api/chat/stream")
    async def chat_stream(request: Request):
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

        def one(event, data, status=200, extra=None):
            async def gen():
                yield sse(event, data)
            return StreamingResponse(gen(), media_type="text/event-stream", headers={**headers, **(extra or {})},
                                     status_code=status)

        # Quota abuse via CSRF: a cross-site "simple" POST (text/plain) is not served, and a browser request
        # from a foreign Origin is refused (CORS alone would only have hidden the response from the attacker).
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return JSONResponse({"code": "BAD_INPUT", "message": "Content-Type must be application/json."},
                                status_code=415)
        origin = request.headers.get("origin")
        # Same-origin requests (the page served by this app, on whatever host the Space runs) are always allowed;
        # a browser sets Host to the real target, so a cross-site page cannot fake this match.
        same_origin = bool(origin) and origin.split("://", 1)[-1].rstrip("/").lower() == \
            (request.headers.get("host") or "").lower()
        if origin and not same_origin and origin not in s.allowed_origins:
            return JSONResponse({"code": "BAD_INPUT", "message": "Origin not allowed."}, status_code=403)
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            body = None

        if not isinstance(body, dict) or not isinstance(body.get("message"), str):
            return one("error", {"code": "BAD_INPUT", "message": "Body must be JSON with a string 'message'."})
        msg = body["message"]
        lang = body.get("lang") if body.get("lang") in ("auto", "en", "ar") else "auto"
        history = body.get("history") if isinstance(body.get("history"), list) else []
        if len(history) > 8:
            history = history[-8:]
        ok, retry = limiter.check(_client_ip(request, s.trusted_proxy_hops))
        if ok and s.llm_available:
            ok, retry = budget.check()
        if not ok:
            # 429 + Retry-After so proxies and monitoring see the throttling; the SSE error frame is the contract.
            return one("error", {"code": "RATE_LIMITED", "retry_after_s": retry,
                                 "message": templates.t("rate_limited", detect_lang(msg, lang))},
                       status=429, extra={"Retry-After": str(retry)})
        req = ChatRequest(session_id=str(body.get("session_id") or "")[:64], message=msg, history=history, lang=lang)

        async def gen():
            try:
                async for ev, data in engine.run(req):
                    yield sse(ev, data)
            except Exception as e:  # noqa: BLE001
                log.exception("chat failed: %s", type(e).__name__)
                yield sse("error", {"code": "INTERNAL", "message": "Something went wrong. Please try again."})

        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

    chips_cache = starter_chips(store)

    def backup_meta() -> dict:  # BACKUP-PROVIDER HOOK
        if engine.llm is not None and hasattr(engine.llm, "cfg") and callable(getattr(engine.llm, "meta", None)):
            return engine.llm.meta()
        return {"enabled": False, "provider": None, "model": None, "used": 0, "cap": 0}

    def llm_meta() -> dict:
        router = getattr(engine.llm, "router", None)
        mode = s.llm_mode_label
        if mode == "off" or engine.llm is None or router is None:
            return {"mode": "off", "state": "off", "budget": {"used": 0, "cap": s.llm_daily_budget}, "pool": [],
                    "backup": backup_meta()}
        state = "maintenance" if s.maintenance_mode else router.state
        return {"mode": mode, "state": state, "budget": router.budget(), "pool": router.snapshot(),
                "backup": backup_meta()}

    # ------------------------------------------------------------------ data
    @app.get("/api/meta")
    async def meta():
        llm_info = llm_meta()
        return {
            "dataset_version": store.version, "data_as_of": store.data_as_of, "counts": store.counts(),
            "counts_by_site": {site: {"projects": sum(1 for p in store.projects if str(p.get("site") or "").lower() == site.lower()),
                                      "listings": sum(1 for x in store.listings
                                                      if str(x.get("site") or "Wasalt").lower() == site.lower())}
                               for site in ("DarGlobal", "Wasalt")},
            "completeness": _flat_completeness(store.meta.get("completeness") or {}), "models": s.openrouter_models,
            "llm_available": llm_info["state"] == "ok", "flags": s.flags,
            "candidate": s.candidate, "retrieval": retriever.mode, "maintenance_mode": s.maintenance_mode,
            "coverage": store.coverage(), "llm": llm_info, "starter_chips": chips_cache,
        }

    @app.get("/api/flags")
    async def flags():
        return {f: bool(s.flags.get(f)) for f in FLAG_NAMES}

    @app.get("/api/projects")
    async def projects(city: str | None = None, country: str | None = None, site: str | None = None,
                       lang: str = "en"):
        return [project_card(p, lang) for p in store.filter_projects(city=city, country=country, site=site)]

    @app.get("/api/projects/{slug}")
    async def project(slug: str):
        p = store.project_by_id(slug)
        if not p:
            return JSONResponse({"code": "NOT_FOUND", "message": "Project not found."}, status_code=404)
        return {**{k: v for k, v in p.items() if k != "content_hash"}, **store.licence_for(p)}

    @app.get("/api/listings")
    async def listings(city: str | None = None, listing_type: str | None = None, min: float | None = None,
                       max: float | None = None, beds: int | None = None):
        if listing_type not in (None, "buy", "rent"):
            return JSONResponse({"code": "BAD_INPUT", "message": "listing_type must be buy or rent."}, status_code=400)
        return [listing_card(x) for x in store.filter_listings(city=city, listing_type=listing_type, min_price=min,
                                                               max_price=max, beds=beds)]

    @app.post("/api/compare")
    async def compare(request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or len(ids) != 2 or not all(isinstance(i, str) for i in ids):
            return JSONResponse({"code": "BAD_INPUT", "message": "Provide ids: [a, b]."}, status_code=400)
        payload = compare_payload(store, ids, body.get("lang", "en") if body.get("lang") in ("en", "ar") else "en")
        if not payload:
            return JSONResponse({"code": "NOT_FOUND", "message": "Both ids must exist and be the same kind."},
                                status_code=404)
        return payload

    @app.get("/api/evals")
    async def evals():
        for path in (os.environ.get("EVALS_PATH", ""), "evals/results/latest.json", "/app/evals/results/latest.json"):
            if path and os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        return json.load(f)
                except (OSError, ValueError):
                    break
        return {}

    # --- showcase (Stress-tested block): data/showcase.json, written by evals/make_showcase.py from recorded runs ---
    @app.get("/api/showcase")
    async def showcase():
        for path in (os.environ.get("SHOWCASE_PATH", ""), "data/showcase.json", "/app/data/showcase.json"):
            if path and os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        d = json.load(f)
                    return d if isinstance(d, dict) else {}
                except (OSError, ValueError):
                    break
        return {}
    # --- end showcase ---

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz(request: Request):
        ready = store.loaded
        # Count only (never the addresses): how many X-Forwarded-For hops reached us, so the owner can set
        # TRUSTED_PROXY_HOPS for the host (see deploy/README.md).
        xff = [h for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
        body = {"ready": ready, "dataset_loaded": store.loaded, "retrieval": retriever.mode,
                "index": retriever.index_state, "llm": llm_meta()["state"], "xff_hops_seen": len(xff),
                "llm_configured": s.llm_available, "maintenance_mode": s.maintenance_mode}
        return JSONResponse(body, status_code=200 if ready else 503)

    # ------------------------------------------------------------------ static + SPA fallback
    static_root = os.path.abspath(s.static_dir)

    def _safe(path: str) -> str | None:
        full = os.path.abspath(os.path.join(static_root, path.lstrip("/")))
        if not full.startswith(static_root + os.sep) and full != static_root:
            return None
        return full if os.path.isfile(full) else None

    def _not_found(api: bool):
        if api:
            return JSONResponse({"code": "NOT_FOUND", "message": "Not found."}, status_code=404)
        f = _safe("404.html")
        if f:
            return FileResponse(f, status_code=404, media_type="text/html")
        return HTMLResponse("<!doctype html><title>Not found</title><h1>Page not found</h1><a href='/'>Home</a>",
                            status_code=404)

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def static_files(full_path: str):
        path = "/" + full_path
        if path.startswith("/api/"):
            return _not_found(True)
        if (path.rstrip("/") == "/demo" or path.startswith("/demo/")) and not s.flags.get("FF_WIDGET_DEMO"):
            return _not_found(False)  # the widget demo does not exist on a deployment where its flag is off
        f = _safe(full_path) if full_path else None
        if f:
            long_cache = "/_next/static/" in path
            return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable" if long_cache
                                            else "public, max-age=300"})
        route = path.rstrip("/") or "/"
        if route in SPA_ROUTES:
            stem = route.strip("/")
            for cand in ([f"{stem}.html", f"{stem}/index.html"] if stem else []) + ["index.html"]:
                f = _safe(cand)
                if f:
                    return FileResponse(f, media_type="text/html", headers={"Cache-Control": "no-cache"})
            return HTMLResponse("<!doctype html><title>Concierge</title><p>Frontend not built.</p>")
        return _not_found(False)

    return app


app = create_app()
