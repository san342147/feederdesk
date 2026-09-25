# LinkedIn draft — review before publishing

I built FeederDesk, a local power incident desk for a facility team. An operator can record an outage, revise its ETA, and confirm each change. A resident can select an area and see the latest staff report with its source and last confirmed update time.

The engineering focus was a reliable tool harness: four allowlisted, schema-validated read tools; per-call timeouts; bounded retries only for transient read failures; and a visible trace of each call. The app also works without an LLM key.

In my local run on 25 September 2026, the seven automated tests passed. I also walked through a browser lookup and an operator update. The current demo uses synthetic training data and has no live utility feed. Before use by a real facility, I would validate the workflow with staff and residents and complete that organization's security and operational review.

[Add repository URL and a verified screenshot after publication.]
