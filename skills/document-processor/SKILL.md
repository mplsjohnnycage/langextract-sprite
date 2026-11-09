---
name: langextract-sprite-document-processor
description: Prepare documents and examples for the Sprite LangExtract extraction queue.
---

# Document processor

1. Keep original text byte-identical (UTF-8 decoded to Python string), and do not rewrite it before hashing or chunking.
2. Create the input payload `{"document_text": string, "instructions": string, "examples":[{"text": string,"extractions":[{"extraction_class":string,"extraction_text":string}]}], "max_char_buffer":1000}`.
3. Examples must be real aligned sample spans (or explicit synthetic illustrations), labeled separately from source. Avoid examples that prejudge disputed claims.
4. For small inputs run `python -m bridge.cli create --data '<JSON>'` using an array-style Sprite exec; for long or sensitive inputs use `mcp__Sprites__file_write` into `<PROJECT_DIR>/data/inputs/<job>-payload.json` (mode 0600), then `create --file` for that absolute path. Never paste private material into logs or public URLs.
5. LangExtract 1.7.2 performs native chunking and prompt construction. Save the returned job ID and source SHA-256. Do not recompute normalized offsets.
6. Inputs over 250,000 characters are rejected; max_char_buffer must be 64–10,000; document splitting above the cap requires a deliberate multi-job scheme without cross-job offset claims.
