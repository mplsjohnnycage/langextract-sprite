---
name: langextract-sprite-validation-recovery
description: REQUIRED fail-closed validation, recovery, and completion checks for LangExtract Sprite jobs.
---

# Mandatory validation and recovery

1. **MUST** use the deterministic gateway to manage state. The complete sequence is `doctor`, `start`/`resume`, `next`, active inference, `submit`, and `finish`; `repair` is only for failed jobs. **MUST NOT** fabricate a successful call or infer state from a previous conversation.
2. **MUST** inspect the JSON `ok` on every script call. A nonzero exit or `ok=false` **MUST** block success. If a submission fails, inspect current job status/error through `bridge.tools` and reconcile IDs/payloads. **MUST NOT** retry with guessed batch IDs, mutate original source text, or overwrite an already accepted response.
3. If native LangExtract finalization fails, **MUST** identify the failed job and exact prompt before calling gateway `repair --job-id JOB_ID --prompt-id PROMPT_ID`. Repair **MUST NOT** be used on completed jobs. After repair, **MUST** fetch, reason, and submit the corrected batch, then finish again.
4. **MUST** use gateway `finish --job-id JOB_ID` to verify **all** of the following before reporting success: `state=completed`, `pending=0`, result available, stored SHA-256 equals status SHA-256, audit `ok=true` with zero issues, response count equals total prompts, verified span count equals recorded span count, and **zero unverified extractions**. **MUST NOT** bypass this gate with a basic `status` call.
5. **MUST** output verified quotes with their exact `start`/`end` offsets; model assertions, interpretations, and document allegations are **not** independent facts merely because offsets match.
6. On interruption, **MUST** preserve the durable job ID and pending count, explain that ChatGPT is not running in the background, and state `resume --job-id JOB_ID` as the next action. **MUST NOT** claim completion when it has not passed `finish`.
