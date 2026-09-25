# FeederDesk

FeederDesk is a facility-operated power incident desk for campus or apartment staff. An operator records an outage or restoration update once; a resident selects an area and sees the latest report, source note, and confirmed update time. The included directory and incident are **synthetic training data**. FeederDesk does not connect to a DISCOM or utility feed.

## Run locally on Windows

Requires Python 3.12. From this folder:

```powershell
.\start.ps1
```

Open <http://127.0.0.1:8000>. The first run creates `.venv`, installs locked dependencies, and creates `data/demo.db`. Search for `Nandanam Block B`, select it, review the proposed `outage_status` call, and run it. The operator demo password is `demo-operator`. All data is synthetic. Use `Ctrl+C` to stop.

If PowerShell blocks scripts, run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

To reset **only** the demo database:

```powershell
$env:FEEDERDESK_MODE='demo'
.\.venv\Scripts\python.exe -m scripts.demo_reset
```

Copy `.env.example` values into environment variables for your shell or service. The app does not load `.env` automatically.

## Main journey

1. A resident searches the facility directory and selects an area. The UI proposes a specific, validated read tool with its arguments. They run or cancel it.
2. The result shows status, estimate if known, source, and last confirmed time. A missing report says **no report**, not “power available.” The session trace shows tool name, arguments, status, elapsed time, and retries.
3. An operator signs in and can add areas with public contact channels, reviewing a confirmation dialog before each addition. This initializes a fresh production database without demo fixtures.
4. The operator creates an incident and explicitly reviews a confirmation dialog before saving. To revise status or ETA, they select the existing report, edit, and confirm again. Revisions remain in SQLite.

The intended user workflow is a hypothesis until observed with a facility operator and resident. No user interviews or live facility validation are claimed.

## Architecture and data

The browser is static HTML/CSS/JavaScript served by FastAPI. `app.main` owns HTTP routes and cookie authentication; `app.harness` allowlists four typed Pydantic tools; `app.db` provides SQLite schema and transactions. Tables are `areas`, `incidents`, `incident_revisions`, `tool_audit`, and `schema_migrations`. Database files, secrets, and virtual environments are ignored by Git.

The tools are `list_areas`, `outage_status`, `eta_minutes`, and `contact_channel`. Read calls have a 1.5 second timeout and at most three attempts with bounded exponential backoff. Only timeout and transient 503 failures retry. Unknown tools, malformed arguments, 404s, and writes do not retry. An optional model could propose a tool only through the same allowlisted endpoint; this release uses a deterministic form and needs no model key. Tool output is displayed as data, never executed as instructions.

Write routes require an operator session, CSRF token, and `confirmed: true`. Cookies are HTTP-only and SameSite Strict. Production mode requires a configured password and a session secret of at least 32 characters; its cookie is `Secure`, so serve it behind HTTPS. There is a basic per-process sign-in attempt limit. This is a small single-facility service, not a multi-tenant identity system.

## Production configuration

Set `FEEDERDESK_MODE=production`, `FEEDERDESK_DB` to a persistent, writable database path, `FEEDERDESK_OPERATOR_PASSWORD` to a unique strong password, and `FEEDERDESK_SESSION_SECRET` to a random value of at least 32 characters. Terminate HTTPS at a trusted reverse proxy, restrict host and origin at the proxy, and back up the SQLite database. Do not run the demo reset command against operational data. Use an organization's approved incident process and review source notes for private information before deployment.

`GET /healthz` checks SQLite availability. For backup, stop writes or use SQLite's online backup API, store an encrypted copy outside the app host, and test a restore before relying on it. Retain or purge audit and revision records according to the facility's policy. The application logs errors through the server but does not log passwords or request bodies.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp
```

The tests cover the operator create/query/update journey, fresh production directory setup, unauthenticated and unconfirmed writes, duplicate open reports, tool allowlisting and schema validation, timeout and 503 retries, non-retryable 404s, and non-idempotent no-retry behavior. CI runs the same test suite on Windows with Python 3.12. On 2026-09-25, the local suite passed **7 tests**; see the current command output for a fresh result. A browser walkthrough also exercised resident lookup, operator sign-in, confirmation, and update.

## Limits

This is an operator-maintained local desk. It has no live utility integration, SMS dispatch, verified restoration forecast, or resident accounts. The ETA is a staff estimate associated with its update time, not a guarantee. Production rollout needs facility authorization, user testing, HTTPS, backup monitoring, and a proper identity provider if multiple staff need individual audit attribution. The demo operator identity is shared, so revision actors are labeled `operator`.

## Screenshots

The screenshots were captured from the running synthetic demo after an operator ETA update: [desktop](docs/screenshots/feederdesk-desktop.jpg) and [phone width](docs/screenshots/feederdesk-mobile.jpg).

See [demo script](docs/demo-script.md), [decision log](docs/decision-log.md), and [LinkedIn draft](docs/linkedin-draft.md).
