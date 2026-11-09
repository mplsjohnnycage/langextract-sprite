---
name: langextract-sprite-validation-recovery
description: Validate and recover evidence-grounded LangExtract extraction jobs running on a Sprite.
---

# Validation and recovery

- Run `langextract.status` and `langextract.result` through the fixed Sprite-side `bridge.tools` dispatcher with existing Sprites MCP.
- Finalized results are parsed and aligned by **native LangExtract**; `verified_extractions` have exact source character offsets and matched verbatim source text. `unverified_extractions` are explicitly excluded from verified evidence.
- Verify `source_sha256` against original document; do not treat model-produced claims as independently true merely because their source text is present.
- Invalid JSON submissions are rejected atomically; fix the response and retry using the original batch_id.
- Identical duplicate submissions are idempotent. Conflicting resubmissions are rejected, not overwritten.
- If LangExtract finalization fails, read `status.error` and inspect the relevant prompt. Use `langextract.repair` through the dispatcher to reopen a failed job's specific prompt, then fetch and submit a corrected batch. Do not change original source text.
- Interrupted runs remain `awaiting_model` with SQLite state across process restarts. For true permanent background inference, explicitly authorize a separate model API; Sprite alone cannot call the current conversation.

- Before final reporting, invoke `langextract.audit` via the dispatcher and require `result.ok == true`; check `result.state == "completed"`.
