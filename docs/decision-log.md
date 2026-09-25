# Decisions

- **Source of truth:** SQLite stores operator entries. There is no implied live feed. The synthetic demo database is selected only in demo mode.
- **No model dependency:** Residents use explicit search and proposed tool calls. The harness still validates every tool name and argument, making future model proposals subject to the same boundary.
- **Retry scope:** Only idempotent reads retry on timeout or transient 503. Writes require a separate authenticated confirmation and are never run by the harness.
- **One open report per area:** The service rejects a second open incident for an area and directs the operator to update the current report.
- **Fresh directory setup:** Operators add areas and public contact channels through the same authenticated confirmation boundary. Production starts with no fixtures.
- **Visual system:** Deep green electrical cabinet panels and signal yellow separate FeederDesk from Project 1's charcoal parking-bay theme. Status text accompanies every color.
