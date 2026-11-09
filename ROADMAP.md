# LangExtract Sprite extension roadmap

Primary goal: make Google LangExtract usable **without an external model API key**, with an active ChatGPT conversation as the inference engine and a ChatGPT plugin/skills orchestrating an existing authenticated Fly Sprites MCP connection. Build reusable infrastructure around LangExtract without duplicating native chunking, provider routing, source alignment, or visualization.

## Shipped in 0.1.0

- Native LangExtract chunk capture and model-response replay.
- SQLite WAL persistent jobs and original-source SHA-256.
- Restart-safe prompt submissions, duplicate idempotency and conflict rejection.
- Invalid response validation and failed-job repair.
- Job listing without source disclosure and audit of source/response integrity and grounded spans.
- ChatGPT/Sprites MCP reference workflow requiring an authenticated connector and active inference turn.
- Fixed Sprite-side JSON tool dispatcher for eight LangExtract operations through the existing Fly MCP `exec` tool; not a new MCP server.

## Planned, not implemented

1. **Provider-agnostic adapter SDK** for local models, agents, external models and human reviewers.
2. **Provenance ledger** with revisions, evidence chains and contradiction review.
3. **Document ingestion** for PDF, Office files and audio, preserving original source mappings.
4. **Scale** via worker leases, claim timeouts, migrations and pluggable durable storage.
5. **Inspection and export** with JSONL and LangExtract-native visualizations.
6. **Evaluation and security** datasets, reproducible provider tests and auditing.
7. **Multi-tenant deployment** with authentication, policy-aware retention and isolation.

Contribute generally useful changes to google/langextract upstream instead of maintaining a divergent fork.
