import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.harness import ToolSpec, TransientToolError
from app.main import create_app
from app.models import AreaArgs


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "test.db"), mode="demo"))


def login(client):
    response = client.post("/api/login", json={"password": "demo-operator"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def incident_payload(area_id=1):
    return {"area_id": area_id, "status": "outage",
            "started_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "eta_minutes": 45, "source_note": "Confirmed by facility operator", "confirmed": True}


def test_operator_journey_and_confirmed_timestamp(client):
    headers = login(client)
    created = client.post("/api/incidents", json=incident_payload(), headers=headers)
    assert created.status_code == 201
    incident_id = created.json()["id"]
    first = client.post("/api/tools/run", json={"name": "outage_status", "arguments": {"area_id": 1}}).json()
    assert first["result"]["eta_minutes"] == 45
    updated = client.put(f"/api/incidents/{incident_id}", headers=headers,
                         json={"status": "restoring", "eta_minutes": 20,
                               "source_note": "Crew confirmed repair in progress", "confirmed": True})
    assert updated.status_code == 200
    second = client.post("/api/tools/run", json={"name": "outage_status", "arguments": {"area_id": 1}}).json()
    assert second["result"]["eta_minutes"] == 20
    assert second["result"]["updated_at"] == updated.json()["updated_at"]
    assert client.get("/api/audit").status_code == 200


def test_write_guards_and_conflict(client):
    payload = incident_payload()
    assert client.post("/api/incidents", json=payload).status_code == 401
    headers = login(client)
    assert client.post("/api/incidents", json=payload).status_code == 403
    assert client.post("/api/incidents", headers=headers, json={**payload, "confirmed": False}).status_code == 409
    assert client.post("/api/incidents", headers=headers, json=payload).status_code == 201
    assert client.post("/api/incidents", headers=headers, json=payload).status_code == 409
    assert client.post("/api/incidents", headers=headers, json={**payload,"eta_minutes":-1}).status_code == 422


def test_tool_allowlist_and_validation(client):
    unknown = client.post("/api/tools/run", json={"name": "delete_all", "arguments": {}}).json()
    invalid = client.post("/api/tools/run", json={"name": "outage_status", "arguments": {"area_id": "oops"}}).json()
    assert unknown["status"] == "rejected" and unknown["attempts"] == 0
    assert invalid["status"] == "rejected" and invalid["attempts"] == 0


def test_retry_timeout_and_503_are_bounded(client):
    harness = client.app.state.harness
    harness.timeout = 0.01
    harness.backoff = 0
    calls = 0

    async def slow(args):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)
        return {}

    harness.tools["outage_status"] = ToolSpec(AreaArgs, slow)
    timeout = client.post("/api/tools/run", json={"name": "outage_status", "arguments": {"area_id": 1}}).json()
    assert timeout["status"] == "failed" and timeout["attempts"] == 3 and calls == 3
    calls = 0

    async def transient(args):
        nonlocal calls
        calls += 1
        raise TransientToolError("Simulated 503")

    harness.tools["outage_status"] = ToolSpec(AreaArgs, transient)
    failure = client.post("/api/tools/run", json={"name": "outage_status", "arguments": {"area_id": 1}}).json()
    assert failure["status"] == "failed" and failure["attempts"] == 3 and calls == 3


def test_non_transient_error_not_retried(client):
    result = client.post("/api/tools/run", json={"name": "outage_status", "arguments": {"area_id": 999}}).json()
    assert result["status"] == "failed" and result["http_status"] == 404 and result["attempts"] == 1


def test_non_idempotent_tool_never_retries(client):
    harness = client.app.state.harness
    calls = 0

    async def unavailable(args):
        nonlocal calls
        calls += 1
        raise TransientToolError("Simulated 503")

    harness.tools["test_write"] = ToolSpec(AreaArgs, unavailable, idempotent=False)
    result = client.post("/api/tools/run", json={"name": "test_write", "arguments": {"area_id": 1}}).json()
    assert result["status"] == "failed" and result["attempts"] == 1 and calls == 1


def test_fresh_production_database_can_be_initialized(tmp_path, monkeypatch):
    monkeypatch.setenv("FEEDERDESK_OPERATOR_PASSWORD", "test-only-password")
    monkeypatch.setenv("FEEDERDESK_SESSION_SECRET", "test-only-secret-which-is-long-enough-123")
    fresh = TestClient(create_app(str(tmp_path / "fresh.db"), mode="production"), base_url="https://testserver")
    assert fresh.post("/api/tools/run", json={"name": "list_areas", "arguments": {}}).json()["result"]["areas"] == []
    area = {"name": "South Tower", "zone": "South campus", "contact": "Facility desk extension 401",
            "contact_source": "Manager-verified directory", "confirmed": True}
    assert fresh.post("/api/areas", json=area).status_code == 401
    auth = fresh.post("/api/login", json={"password": "test-only-password"})
    headers = {"X-CSRF-Token": auth.json()["csrf"]}
    assert fresh.post("/api/areas", json={**area, "confirmed": False}, headers=headers).status_code == 409
    created = fresh.post("/api/areas", json=area, headers=headers)
    assert created.status_code == 201
    assert fresh.post("/api/areas", json=area, headers=headers).status_code == 409
    incident = fresh.post("/api/incidents", json=incident_payload(created.json()["id"]), headers=headers)
    assert incident.status_code == 201
    result = fresh.post("/api/tools/run", json={"name": "outage_status", "arguments": {"area_id": created.json()["id"]}}).json()
    assert result["result"]["area"] == "South Tower"
