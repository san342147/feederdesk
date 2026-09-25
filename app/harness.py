from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel, ValidationError

from .db import Store
from .models import AreaArgs, ContactArgs, ListArgs, utc_now


class ToolError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class TransientToolError(ToolError):
    def __init__(self, message: str = "Service temporarily unavailable"):
        super().__init__(message, 503)


@dataclass(frozen=True)
class ToolSpec:
    args: type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[dict]]
    idempotent: bool = True


class Harness:
    def __init__(self, store: Store, timeout: float = 1.5, max_attempts: int = 3, backoff: float = 0.05):
        self.store = store
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.tools: dict[str, ToolSpec] = {
            "list_areas": ToolSpec(ListArgs, self.list_areas),
            "outage_status": ToolSpec(AreaArgs, self.outage_status),
            "eta_minutes": ToolSpec(AreaArgs, self.eta_minutes),
            "contact_channel": ToolSpec(ContactArgs, self.contact_channel),
        }

    async def execute(self, name: str, arguments: dict) -> dict:
        trace_id = uuid.uuid4().hex
        started = time.perf_counter()
        spec = self.tools.get(name)
        if not spec:
            return self._finish(trace_id, name, {}, "rejected", 0, started, error="Unknown tool", status=400)
        try:
            args = spec.args.model_validate(arguments)
        except ValidationError:
            return self._finish(trace_id, name, {}, "rejected", 0, started, error="Invalid tool arguments", status=422)
        clean_args = args.model_dump()
        attempts = 0
        while attempts < (self.max_attempts if spec.idempotent else 1):
            attempts += 1
            try:
                result = await asyncio.wait_for(spec.handler(args), timeout=self.timeout)
                return self._finish(trace_id, name, clean_args, "success", attempts, started, result=result)
            except (TimeoutError, TransientToolError) as exc:
                if attempts >= (self.max_attempts if spec.idempotent else 1):
                    message = "Timed out after retries" if isinstance(exc, TimeoutError) else str(exc)
                    return self._finish(trace_id, name, clean_args, "failed", attempts, started, error=message, status=503)
                await asyncio.sleep(self.backoff * (2 ** (attempts - 1)))
            except ToolError as exc:
                return self._finish(trace_id, name, clean_args, "failed", attempts, started, error=str(exc), status=exc.status)
        raise AssertionError("unreachable")

    def _finish(self, trace_id: str, name: str, args: dict, result_status: str, attempts: int,
                started: float, result: dict | None = None, error: str | None = None, status: int = 200) -> dict:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        with self.store.connect() as db:
            db.execute("INSERT INTO tool_audit(trace_id,tool_name,arguments,result_status,elapsed_ms,attempts,occurred_at) VALUES(?,?,?,?,?,?,?)",
                       (trace_id, name, json.dumps(args, sort_keys=True), result_status, elapsed_ms, attempts, utc_now()))
        return {"trace_id": trace_id, "tool": name, "arguments": args, "status": result_status,
                "http_status": status, "elapsed_ms": elapsed_ms, "attempts": attempts,
                "retries": max(0, attempts - 1), "result": result, "error": error}

    async def list_areas(self, args: ListArgs) -> dict:
        with self.store.connect() as db:
            rows = db.execute("SELECT id,name,zone FROM areas WHERE name LIKE ? ORDER BY name LIMIT 30",
                              (f"%{args.query}%",)).fetchall()
            last_update = db.execute("SELECT MAX(contact_updated_at) FROM areas").fetchone()[0]
        return {"areas": [dict(row) for row in rows], "updated_at": last_update, "source": "Operator-maintained facility directory"}

    async def outage_status(self, args: AreaArgs) -> dict:
        with self.store.connect() as db:
            row = db.execute("""SELECT a.id AS area_id,a.name AS area,a.zone,i.id AS incident_id,i.status,
                i.started_at,i.eta_minutes,i.source_note,i.updated_at
                FROM areas a LEFT JOIN incidents i ON i.id=(SELECT id FROM incidents WHERE area_id=a.id ORDER BY updated_at DESC,id DESC LIMIT 1)
                WHERE a.id=?""", (args.area_id,)).fetchone()
        if not row:
            raise ToolError("Area not found", 404)
        record = dict(row)
        if record["incident_id"] is None:
            record.update(status="no_report", updated_at=None, source="No operator report")
        else:
            record["source"] = record.pop("source_note")
        return record

    async def eta_minutes(self, args: AreaArgs) -> dict:
        record = await self.outage_status(args)
        return {key: record.get(key) for key in ("area_id", "area", "status", "eta_minutes", "updated_at", "source")}

    async def contact_channel(self, args: ContactArgs) -> dict:
        with self.store.connect() as db:
            row = db.execute("SELECT name AS area,contact AS channel,contact_source AS source,contact_updated_at AS updated_at FROM areas WHERE id=?",
                             (args.area_id,)).fetchone()
        if not row:
            raise ToolError("Area not found", 404)
        return dict(row)
