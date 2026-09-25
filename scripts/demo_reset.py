"""Reset only the synthetic demo database; never run against production data."""
import os
from pathlib import Path

from app.db import Store

if os.getenv("FEEDERDESK_MODE", "demo") != "demo":
    raise SystemExit("Demo reset is disabled outside demo mode")

path = Path(os.getenv("FEEDERDESK_DB", "data/demo.db")).resolve()
if path.name != "demo.db":
    raise SystemExit("Refusing to reset a database that is not named demo.db")
if path.exists():
    path.unlink()
Store(str(path)).seed_demo()
print(f"Synthetic demo database reset: {path}")
