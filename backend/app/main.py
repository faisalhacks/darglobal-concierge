"""FastAPI entry point. Run: uvicorn backend.app.main:app --port 7860 --no-access-log

Serves /api/* and the static Next.js export (STATIC_DIR) at /. Built for a Hugging Face Docker Space
(port 7860, non-root uid 1000); the same image runs on Render.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import templates
from .arabic import detect_lang
from .chat import ChatRequest, Engine
from .config import FLAG_NAMES, Settings, load_settings
from .llm import MockLLM, OpenRouterClient
from .retrieval import Retriever
from .store import Store, compare_payload, listing_card, project_card

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


CSP = ("default-src 'self'; img-src 'self' https: data:; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; "
       "connect-src 'self'; frame-ancestors 'self' https://huggingface.co https://*.hf.space; "
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


class BodyLimit(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max = max_bytes

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > self.max:
                return JSONResponse({"code": "BAD_INPUT", "message": "Request too large."}, status_code=413)
        return await call_next(request)


def _client_ip(request: Request) -> str:
    # HF Spaces / Render sit behind a proxy; use the first X-Forwarded-For hop when present.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _make_llm(s: Settings):
    if s.llm_mode == "mock":
        return MockLLM(fail_with=os.environ.get("MOCK_LLM_FAIL") or None)
    if s.llm_available:
        return OpenRouterClient(s)
    return None


def create_app(settings: Settings | None = None, llm=None, embedder=None) -> FastAPI:
    s = settings or load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("uvicorn.access").disabled = True  # access logs contain client IPs

    store = Store.load(s.data_path)
    retriever = Retriever(store, s.index_dir, s.embeddings, s.embed_cache_dir, s.retrieval_threshold,
                          embedder=embedder)
    engine = Engine(s, store, retriever, llm if llm is not None else _make_llm(s))
    limiter = RateLimiter(s.rate_limit_n, s.rate_limit_window_s)

    app = FastAPI(title="Property Concierge (candidate prototype)", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.settings, app.state.store, app.state.engine, app.state.retriever = s, store, engine, retriever
    app.state.limiter = limiter
    app.add_middleware(BodyLimit, max_bytes=s.max_body_bytes)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], allow_credentials=False, max_age=600)

    # ------------------------------------------------------------------ chat
    @app.post("/api/chat/stream")
    async def chat_stream(request: Request):
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            body = None
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

        def one(event, data, status=200):
            async def gen():
                yield sse(event, data)
            return StreamingResponse(gen(), media_type="text/event-stream", headers=headers, status_code=status)

        if not isinstance(body, dict) or not isinstance(body.get("message"), str):
            return one("error", {"code": "BAD_INPUT", "message": "Body must be JSON with a string 'message'."})
        msg = body["message"]
        lang = body.get("lang") if body.get("lang") in ("auto", "en", "ar") else "auto"
        history = body.get("history") if isinstance(body.get("history"), list) else []
        if len(history) > 8:
            history = history[-8:]
        ok, retry = limiter.check(_client_ip(request))
        if not ok:
            return one("error", {"code": "RATE_LIMITED", "retry_after_s": retry,
                                 "message": templates.t("rate_limited", detect_lang(msg, lang))})
        req = ChatRequest(session_id=str(body.get("session_id") or "")[:64], message=msg, history=history, lang=lang)

        async def gen():
            try:
                async for ev, data in engine.run(req):
                    yield sse(ev, data)
            except Exception as e:  # noqa: BLE001
                log.exception("chat failed: %s", type(e).__name__)
                yield sse("error", {"code": "INTERNAL", "message": "Something went wrong. Please try again."})

        return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

    # ------------------------------------------------------------------ data
    @app.get("/api/meta")
    async def meta():
        return {
            "dataset_version": store.version, "data_as_of": store.data_as_of, "counts": store.counts(),
            "completeness": _flat_completeness(store.meta.get("completeness") or {}), "models": s.openrouter_models,
            "llm_available": s.llm_available and not s.maintenance_mode, "flags": s.flags,
            "candidate": s.candidate, "retrieval": retriever.mode, "maintenance_mode": s.maintenance_mode,
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
        return {k: v for k, v in p.items() if k != "content_hash"}

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

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        ready = store.loaded
        body = {"ready": ready, "dataset_loaded": store.loaded, "retrieval": retriever.mode,
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
