from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .db import Store
from .harness import Harness
from .models import AreaInput, IncidentInput, IncidentUpdate, ToolRequest, utc_now

ROOT = Path(__file__).resolve().parent.parent


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=200)


class CreateInput(IncidentInput):
    confirmed: bool


class UpdateInput(IncidentUpdate):
    confirmed: bool


class CreateAreaInput(AreaInput):
    confirmed: bool


def create_app(db_path: str | None = None, mode: str | None = None) -> FastAPI:
    app_mode = mode or os.getenv("FEEDERDESK_MODE", "demo")
    if app_mode not in {"demo", "production"}:
        raise RuntimeError("FEEDERDESK_MODE must be demo or production")
    password = os.getenv("FEEDERDESK_OPERATOR_PASSWORD")
    secret = os.getenv("FEEDERDESK_SESSION_SECRET")
    if app_mode == "production" and (not password or not secret or len(secret) < 32):
        raise RuntimeError("Production requires operator password and session secret of at least 32 characters")
    password = password or "demo-operator"
    secret_bytes = (secret or secrets.token_urlsafe(48)).encode()
    path = db_path or os.getenv("FEEDERDESK_DB") or str(ROOT / "data" / ("demo.db" if app_mode == "demo" else "feederdesk.db"))
    store = Store(path)
    if app_mode == "demo":
        store.seed_demo()
    harness = Harness(store)
    app = FastAPI(title="FeederDesk", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.harness = harness
    app.state.mode = app_mode
    login_failures: dict[str, list[float]] = {}
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        try:
            content_length = int(request.headers.get("content-length", "0") or "0")
        except ValueError:
            return JSONResponse({"detail": "Invalid content length"}, status_code=400)
        if request.url.path.startswith("/api") and content_length > 16_384:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "public, max-age=300"
        return response

    def sign(payload: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        signature = hmac.new(secret_bytes, raw.encode(), hashlib.sha256).hexdigest()
        return f"{raw}.{signature}"

    def session(request: Request, csrf: bool = False) -> dict:
        token = request.cookies.get("fd_session", "")
        try:
            raw, signature = token.rsplit(".", 1)
            expected = hmac.new(secret_bytes, raw.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            if payload["exp"] < time.time():
                raise ValueError()
            if csrf and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), payload["csrf"]):
                raise HTTPException(403, "Confirmation session is invalid")
            return payload
        except HTTPException:
            raise
        except (ValueError, KeyError, json.JSONDecodeError, binascii.Error):
            raise HTTPException(401, "Operator sign-in required")

    @app.get("/")
    def home():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/healthz")
    def health():
        try:
            with store.connect() as db:
                db.execute("SELECT 1").fetchone()
            return {"status": "ok", "mode": app_mode}
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.get("/api/meta")
    def meta():
        return {"mode": app_mode, "product": "FeederDesk", "data_notice": "Synthetic training data" if app_mode == "demo" else "Operator-maintained facility data"}

    @app.post("/api/login")
    def login(body: LoginInput, response: Response, request: Request):
        address = request.client.host if request.client else "unknown"
        recent = [stamp for stamp in login_failures.get(address, []) if time.time() - stamp < 300]
        if len(recent) >= 8:
            raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")
        if not hmac.compare_digest(body.password.encode(), password.encode()):
            recent.append(time.time())
            login_failures[address] = recent
            raise HTTPException(401, "Incorrect operator password")
        login_failures.pop(address, None)
        csrf = secrets.token_urlsafe(24)
        token = sign({"exp": int(time.time()) + 8 * 3600, "csrf": csrf, "role": "operator"})
        response.set_cookie("fd_session", token, max_age=8 * 3600, httponly=True, samesite="strict", secure=app_mode == "production", path="/")
        return {"role": "operator", "csrf": csrf}

    @app.get("/api/session")
    def session_info(request: Request):
        try:
            payload = session(request)
            return {"authenticated": True, "role": payload["role"], "csrf": payload["csrf"]}
        except HTTPException:
            return {"authenticated": False}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie("fd_session", path="/")
        return {"ok": True}

    @app.post("/api/tools/run")
    async def run_tool(body: ToolRequest):
        return await harness.execute(body.name, body.arguments)

    @app.post("/api/areas", status_code=201)
    def create_area(body: CreateAreaInput, request: Request):
        session(request, csrf=True)
        if not body.confirmed:
            raise HTTPException(409, "Review and confirm this area")
        name = body.name.strip()
        zone = body.zone.strip()
        contact = body.contact.strip()
        source = body.contact_source.strip()
        if not all((name, zone, contact, source)):
            raise HTTPException(422, "Area fields cannot be blank")
        now = utc_now()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM areas WHERE name=? COLLATE NOCASE", (name,)).fetchone():
                raise HTTPException(409, "An area with this name already exists")
            cursor = db.execute("INSERT INTO areas(name,zone,contact,contact_source,contact_updated_at) VALUES(?,?,?,?,?)",
                                (name, zone, contact, source, now))
        return {"id": cursor.lastrowid, "updated_at": now}

    @app.get("/api/incidents")
    def incidents(request: Request):
        session(request)
        with store.connect() as db:
            rows = db.execute("""SELECT i.id,i.area_id,a.name AS area,i.status,i.started_at,i.eta_minutes,
                i.source_note,i.updated_at FROM incidents i JOIN areas a ON a.id=i.area_id
                ORDER BY i.updated_at DESC,i.id DESC LIMIT 100""").fetchall()
        return {"incidents": [dict(row) for row in rows]}

    @app.post("/api/incidents", status_code=201)
    def create_incident(body: CreateInput, request: Request):
        session(request, csrf=True)
        if not body.confirmed:
            raise HTTPException(409, "Review and confirm this change")
        now = utc_now()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM areas WHERE id=?", (body.area_id,)).fetchone():
                raise HTTPException(404, "Area not found")
            if body.status != "resolved":
                active = db.execute("SELECT id FROM incidents WHERE area_id=? AND status!='resolved' ORDER BY id DESC LIMIT 1", (body.area_id,)).fetchone()
                if active:
                    raise HTTPException(409, "An open incident already exists for this area. Update it instead.")
            cursor = db.execute("INSERT INTO incidents(area_id,status,started_at,eta_minutes,source_note,updated_at,created_by) VALUES(?,?,?,?,?,?,?)",
                                (body.area_id,body.status.value,body.started_at.isoformat(),body.eta_minutes,body.source_note,now,"operator"))
            db.execute("INSERT INTO incident_revisions(incident_id,status,eta_minutes,source_note,changed_at,actor) VALUES(?,?,?,?,?,?)",
                       (cursor.lastrowid,body.status.value,body.eta_minutes,body.source_note,now,"operator"))
        return {"id": cursor.lastrowid, "updated_at": now}

    @app.put("/api/incidents/{incident_id}")
    def update_incident(incident_id: int, body: UpdateInput, request: Request):
        session(request, csrf=True)
        if not body.confirmed:
            raise HTTPException(409, "Review and confirm this change")
        now = utc_now()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            original = db.execute("SELECT area_id FROM incidents WHERE id=?", (incident_id,)).fetchone()
            if not original:
                raise HTTPException(404, "Incident not found")
            if body.status != "resolved":
                active = db.execute("SELECT id FROM incidents WHERE area_id=? AND id!=? AND status!='resolved' LIMIT 1",
                                    (original["area_id"], incident_id)).fetchone()
                if active:
                    raise HTTPException(409, "Another open incident exists for this area")
            db.execute("UPDATE incidents SET status=?,eta_minutes=?,source_note=?,updated_at=? WHERE id=?",
                       (body.status.value,body.eta_minutes,body.source_note,now,incident_id))
            db.execute("INSERT INTO incident_revisions(incident_id,status,eta_minutes,source_note,changed_at,actor) VALUES(?,?,?,?,?,?)",
                       (incident_id,body.status.value,body.eta_minutes,body.source_note,now,"operator"))
        return {"id": incident_id, "updated_at": now}

    @app.get("/api/audit")
    def audit(request: Request):
        session(request)
        with store.connect() as db:
            rows = db.execute("SELECT trace_id,tool_name,arguments,result_status,elapsed_ms,attempts,occurred_at FROM tool_audit ORDER BY id DESC LIMIT 100").fetchall()
        return {"events": [dict(row) for row in rows]}

    return app


app = create_app()
