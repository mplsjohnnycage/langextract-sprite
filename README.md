# LangExtract Sprite

**An independent open-source extension layer for [Google LangExtract](https://github.com/google/langextract).**

LangExtract Sprite adds **durable, auditable, recoverable extraction jobs** around LangExtract's existing native chunking, prompt generation, parsing, and source alignment. It is intended to grow into a general extension platform for LangExtract, not merely a ChatGPT wrapper.

The first inference interface uses an active ChatGPT conversation through an **existing authorized Sprites MCP connector**, without a separate LLM API key. Other clients can use the same persisted prompt-and-response protocol, although first-class provider adapters are not implemented yet.

This is not an official Google or OpenAI project, and it does not fork or vendor LangExtract.

## Added capabilities

- **Persistent jobs:** source text and SHA-256, native prompts, returned responses and response SHA-256 stored in SQLite WAL.
- **Bring-your-own inference:** authorized clients fetch prompts and submit structured responses; ChatGPT actively does the reasoning in its reference workflow.
- **Crash recovery:** jobs survive process restarts; list incomplete jobs, retrieve outstanding prompts and repair native parse failures.
- **Response validation:** malformed submissions rejected, duplicate submissions idempotent and conflicting submissions rejected.
- **Provenance integrity:** audit original text/response hashes and confirm every accepted character interval matches verbatim source text.
- **LangExtract-native processing:** model responses replay through native LangExtract parsing and alignment rather than substituting a custom engine.

Upstream LangExtract itself **already** provides chunking, source alignment, visualizations and model providers. This extension concentrates on long-lived orchestration, auditability, and recovery.

## Architecture

```text
Document + few-shot examples
          |
    LangExtract native prompt capture
          |
    Durable SQLite WAL queue
      |                ^
      v                |
  prompt batches       | model responses
      |                |
      v                |
 authorized inference client
 (ChatGPT / human / future provider adapter)
          |
   LangExtract native response replay
          |
   parse -> align -> source span check
          |
    result + audit + repair
```

No public HTTP listener or second MCP server runs. The reference Sprite deployment calls a Python CLI through the pre-existing Sprites MCP connection.

## Installation

Python 3.12 or later:

```bash
git clone https://github.com/mplsjohnnycage/langextract-sprite.git
cd langextract-sprite
python -m venv .venv
.venv/bin/python -m pip install -e . pytest
.venv/bin/python -m pytest -q
```

The project installs the `langextract-sprite` executable (equivalent to `python -m bridge.cli`). On a source checkout, it saves persistent jobs into `./data/`. When installed as a wheel, the default is `$XDG_STATE_HOME/langextract-sprite`, or `~/.local/state/langextract-sprite` if XDG_STATE_HOME is unset. Override with `LANGEXTRACT_SPRITE_DATA_DIR`.

## API and CLI

First create `data/inputs/job.json`:

```json
{
  "document_text": "Alice joined Acme in March 2025.",
  "instructions": "Extract literal people, organizations, and dates.",
  "max_char_buffer": 1000,
  "examples": [
    {
      "text": "Eve joined Zeta in May 2024.",
      "extractions": [
        {"extraction_class": "person", "extraction_text": "Eve"},
        {"extraction_class": "organization", "extraction_text": "Zeta"},
        {"extraction_class": "date", "extraction_text": "May 2024"}
      ]
    }
  ]
}
```

Then run:

```bash
langextract-sprite create --file "$(pwd)/data/inputs/job.json"
langextract-sprite list --limit 20
langextract-sprite next JOB_ID --limit 3
langextract-sprite submit JOB_ID --file "$(pwd)/data/inputs/responses.json"
langextract-sprite status JOB_ID
langextract-sprite result JOB_ID
langextract-sprite audit JOB_ID
langextract-sprite repair JOB_ID PROMPT_ID
```

The `next` command returns a `batch_id`, `prompt_id` and native LangExtract `prompt_text`. The inference client returns a JSON envelope as a string, for example `{"extractions":[{"person":"Alice"},{"organization":"Acme"},{"date":"March 2025"}]}`. Submission payload shape:

```json
{
  "batch_id": "BATCH_ID_FROM_NEXT",
  "responses": [
    {
      "prompt_id": "PROMPT_ID_FROM_NEXT",
      "response_text": "{\"extractions\":[{\"person\":\"Alice\"}]}"
    }
  ]
}
```

Read `skills/` for a ChatGPT/Sprites reference implementation; skill files are not automatically discoverable without ChatGPT installation/authorization.

## Sprite-side tool interface (no additional MCP server)

The existing Fly Sprites MCP already provides authenticated `exec` and file operations. This project now exposes a **fixed JSON tool dispatcher inside the Sprite**; the ChatGPT plugin and skills call it through the existing `exec` tool. It is **not** a separate MCP server and does not dynamically register tools with Fly MCP.

```bash
python -m bridge.tools '{"tool":"tools.list","arguments":{}}'
python -m bridge.tools '{"tool":"langextract.list","arguments":{"limit":10}}'
python -m bridge.tools '{"tool":"langextract.status","arguments":{"job_id":"JOB_ID"}}'
```

Available tool names: `langextract.create`, `langextract.next`, `langextract.submit`, `langextract.list`, `langextract.status`, `langextract.result`, `langextract.audit`, `langextract.repair`. `tools.list` returns the fixed tool catalog. Each operation returns `{"ok":true,"result":...}` or `{"ok":false,"error":...}`; invalid calls fail closed. The dispatcher does not execute arbitrary shell commands.

This is a **Sprite-side tool protocol**, not eight independently registered MCP tools. To get named tools in ChatGPT's tool picker, a plugin must wrap the dispatcher with the existing Fly Sprites MCP exec call or Fly must support tool registration; that has not been established. Large or sensitive documents should use the protected `data/inputs/` file interface rather than shell arguments.

## Security boundaries

Original document text, prompt text and model responses are sensitive. SQLite state is stored locally; data directories get mode 0700 and DB files mode 0600. The `data/` directory is ignored by Git. For sensitive content, prefer `--file` rather than inline `--data` because process argument lists can expose values. Do not expose the CLI via a public API without explicit authentication and multi-tenant isolation.

Audit results prove **textual integrity and source offsets**, not the factual truth of source claims. The Sprite cannot autonomously call an active ChatGPT conversation; an authorized user session must perform each reasoning turn. This initial version accepts UTF-8 source text and requires few-shot examples. PDF/OCR ingestion, a general adapter SDK, autonomous model workers, and cross-user authorization are future work.

## Contributing and roadmap

See [ROADMAP.md](ROADMAP.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Tests exercise the real LangExtract engine and local SQLite. Real model-inference workflows require separate integration verification.

## License and attribution

Apache-2.0. This project depends on the independently maintained [google/langextract](https://github.com/google/langextract) Python package, which is also Apache-2.0 licensed.

## ChatGPT plugin and skills

The open-source installable ChatGPT plugin template lives in [`plugin/`](plugin/README.md). Configure your authorized Sprite and local Python executable before installing. The plugin uses the existing Fly Sprites MCP `exec` to call `python -m bridge.tools` and needs no additional MCP server or model API key.

## One-command setup (recommended)

On an authorized Fly Sprite with Python 3.12+ and this repository checked out:

```bash
python3 quickstart.py --sprite YOUR_AUTHORIZED_SPRITE --project-dir "$(pwd)"
```

This creates or reuses `.venv`, installs the project (using `uv` if available, otherwise `pip`), verifies all eight Sprite-side operations, and generates `dist/langextract-sprite-chatgpt-plugin.zip` with the correct Sprite name and checkout path. `python3 quickstart.py --help` lists options; `--bundle-only` skips runtime installation.

In ChatGPT, connect and authorize Fly Sprites, upload the generated ZIP as a private ChatGPT plugin where plugin creation is available, and activate it. This command cannot automatically install, authorize, or publicly publish a ChatGPT plugin. Active ChatGPT inference is still required; no external model API key is needed.
