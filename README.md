# LangExtract Sprite

**Use ChatGPT to run Google LangExtract without a separate model API key. Keep extraction jobs durable, auditable, and recoverable on your own Fly Sprite.**

[Quick start](#quick-start) · [How it works](#how-it-works) · [ChatGPT setup](#connect-chatgpt) · [CLI reference](#cli-and-tool-reference) · [Security](#security-and-limitations) · [Roadmap](ROADMAP.md)

> [!IMPORTANT]
> **No separate LLM API key** means ChatGPT performs inference *during an active conversation*. It does **not** mean autonomous background inference or free access to a model outside ChatGPT. You still need an authorized Fly Sprites connection and access to a ChatGPT environment that supports the required plugin/skills workflow.

LangExtract Sprite is an independent, Apache-2.0-licensed orchestration layer built around [Google LangExtract](https://github.com/google/langextract). LangExtract already handles chunking, prompt construction, parsing, and source alignment. This project adds durable jobs, a constrained tool interface, recovery, and integrity checks. It is not affiliated with Google or OpenAI.

## Why use it?

| Capability | What you get |
| --- | --- |
| ChatGPT-powered extraction | Your active ChatGPT session answers LangExtract prompts; no additional model API key |
| Native LangExtract | Upstream chunking, structured parsing, and source-span alignment |
| Persistent jobs | SQLite WAL stores source hashes, prompts, responses, and progress |
| Resume and repair | Restart an interrupted job, retry a failed prompt, reject conflicting submissions |
| Verifiable provenance | Exact source offsets, response hashes, and an audit of stored evidence |
| Existing Fly MCP | Calls the Sprite through its authorized `exec` tool; no extra MCP server |

**Best for:** evidence extraction, research, document analysis, and other tasks where source-grounded results and the ability to resume work matter. **Not yet for:** fully unattended model inference, turnkey multi-user hosting, or PDF/OCR ingestion.

## Quick start

### Prerequisites

- An existing [Fly Sprite](https://sprites.dev/) that you can access through the Fly Sprites connector in ChatGPT.
- Git and Python **3.12+** on that Sprite; network access for Python package installation.
- A ChatGPT environment with access to the authorized Fly Sprites connector and a way to activate the bundled plugin skills. Plugin ZIP upload/installation availability depends on the account or workspace.

### 1. Install on the Sprite

Run this **inside the Sprite** (not on your laptop unless that machine is the intended runtime):

```bash
git clone https://github.com/mplsjohnnycage/langextract-sprite.git
cd langextract-sprite
python3 quickstart.py --sprite YOUR_SPRITE_NAME --project-dir "$(pwd)"
```

Replace `YOUR_SPRITE_NAME` with the name of your **already-authorized** Sprite. The setup script:

1. Creates or reuses `.venv` and installs the Python package (using `uv` if available, otherwise `pip`).
2. Runs a health check against all **eight** LangExtract operations.
3. Generates a personalized ZIP at `dist/langextract-sprite-chatgpt-plugin.zip` containing the correct Sprite name and project path.

Expected final output:

```text
PASS: eight Sprite-side operations available
Plugin ZIP: .../dist/langextract-sprite-chatgpt-plugin.zip
```

Run `python3 quickstart.py --help` for options. Use `--bundle-only` to create a ZIP without reinstalling dependencies. The ZIP is generated **on the Sprite**; transfer it securely to the machine or workflow where you install the ChatGPT plugin.

### 2. Connect ChatGPT

1. Connect and authorize **Fly Sprites** in ChatGPT, granting access to the Sprite named above.
2. Where your ChatGPT account/workspace supports custom plugin installation, import or install the generated plugin ZIP and enable its skills. If that feature is unavailable, use the [bundled skill instructions](plugin/README.md) as a reference with the existing Fly Sprites connector; ZIP generation alone does not install anything.
3. Start a new chat with the plugin enabled and try:

> Extract people, organizations, and dates from “On April 12, 2026, Nora Patel joined Beacon Works.” Use LangExtract Sprite on my authorized Sprite. Return only exact source spans, the job ID, and the audit result.

ChatGPT should create a job, fetch native prompts, generate structured answers, submit them, retrieve the aligned result, and audit it. **Do not claim success unless the result is completed and the audit reports `ok: true`.**

### 3. Check the installation independently

Inside the project on the Sprite:

```bash
.venv/bin/python -m bridge.tools '{"tool":"tools.list","arguments":{}}'
.venv/bin/python -m bridge.tools '{"tool":"langextract.list","arguments":{"limit":5}}'
```

Both commands should return JSON with `"ok": true`. The first returns eight logical operations; the second lists saved jobs. This verifies the **Sprite runtime**, not ChatGPT plugin installation or model inference.

## How it works

```text
Your document + extraction instructions + examples
                         |
                         v
              Google LangExtract
           chunking + native prompts
                         |
                         v
                SQLite WAL queue
                         |
             existing Fly Sprites MCP
                         |
                         v
          ChatGPT in an active session
           reads prompts and reasons
                         |
                         v
               structured responses
                         |
                         v
              Google LangExtract
               parsing + alignment
                         |
                         v
            exact spans + audit report
```

The Sprite never calls ChatGPT as an external API. ChatGPT uses the **existing** Fly Sprites MCP `exec` capability to invoke a fixed Python dispatcher. That dispatcher is **not** a new MCP server, and its eight operations are **not** individually registered MCP tools.

## CLI and tool reference

The installer provides `.venv/bin/langextract-sprite` (equivalent to `.venv/bin/python -m bridge.cli`). Job lifecycle:

| Command | Purpose |
| --- | --- |
| `create` | Persist source text, instructions, and few-shot examples |
| `next` | Fetch the next native LangExtract prompt batch |
| `submit` | Save structured model responses for a batch |
| `list` | List persisted jobs |
| `status` | Check job progress and failures |
| `result` | Retrieve parsed and source-aligned extractions |
| `audit` | Check source/response integrity and aligned spans |
| `repair` | Reopen a failed prompt for correction |

### Create a job

Save this example as `example-job.json`:

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

Then:

```bash
.venv/bin/langextract-sprite create --file "$(pwd)/example-job.json"
.venv/bin/langextract-sprite next JOB_ID --limit 3
```

`next` returns `batch_id`, `prompt_id`, and `prompt_text`. An authorized inference client (such as ChatGPT) reads the prompt and supplies its structured JSON response. Save the following *example shape* as `responses.json`, substituting the actual IDs and response:

```json
{
  "batch_id": "BATCH_ID_FROM_NEXT",
  "responses": [
    {
      "prompt_id": "PROMPT_ID_FROM_NEXT",
      "response_text": "{\"extractions\":[{\"person\":\"Alice\",\"person_attributes\":{}}]}"
    }
  ]
}
```

```bash
.venv/bin/langextract-sprite submit JOB_ID --file "$(pwd)/responses.json"
.venv/bin/langextract-sprite status JOB_ID
.venv/bin/langextract-sprite result JOB_ID
.venv/bin/langextract-sprite audit JOB_ID
# Only if a prompt needs recovery:
.venv/bin/langextract-sprite repair JOB_ID PROMPT_ID
```

Repeat `next` and `submit` until the job is complete. Do not assume the sample response is a full extraction of the source; it illustrates the submission format.

### JSON tool dispatcher

The ChatGPT skills use `.venv/bin/python -m bridge.tools` through Fly Sprites MCP `exec`:

```bash
.venv/bin/python -m bridge.tools '{"tool":"langextract.status","arguments":{"job_id":"JOB_ID"}}'
```

Tool names are `langextract.create`, `langextract.next`, `langextract.submit`, `langextract.list`, `langextract.status`, `langextract.result`, `langextract.audit`, and `langextract.repair`. `tools.list` describes their arguments. Requests use `{"tool":"...","arguments":{...}}`; success returns `{"ok":true,...}` and errors return `{"ok":false,"error":"..."}`. Unknown tools and unexpected arguments are rejected.

## Verification

The project has automated tests for the native extraction bridge, dispatcher, and setup bundle. Run:

```bash
.venv/bin/python -m pip install pytest  # if pip is available; otherwise: uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest -q
```

On the reference Sprite, **16 tests passed** after the quick-start implementation. A separate live ChatGPT-driven extraction produced three exact source spans and passed its audit. These checks demonstrate the reference deployment; they do not guarantee every external account can install a custom plugin.

## Security and limitations

- **Keep private text out of command arguments** when possible: process listings/logs may expose them. Prefer protected input files and the CLI `--file` option for sensitive or large payloads.
- **Protect local state:** the project stores source text and responses in SQLite. Its data directory is private to the Sprite; do not publish the database or expose the CLI as an unauthenticated web service.
- **Evidence is not truth:** exact span alignment proves that a string occurs in the source, not that the source's claim is correct.
- **ChatGPT must be active:** the Sprite cannot initiate unattended ChatGPT reasoning. Long jobs may require continued active turns.
- **Not a public MCP endpoint:** this integration relies on each user's authorized Fly Sprites connection. The plugin template is open source, but ChatGPT directory publication and installation are separate processes.
- **Current input:** UTF-8 text with few-shot examples. PDF/OCR ingestion, multi-tenant authorization, and autonomous provider adapters are not implemented.

Persistent data defaults to `./data/` for source checkouts and to `$XDG_STATE_HOME/langextract-sprite` (or `~/.local/state/langextract-sprite`) for wheel installs. Override using `LANGEXTRACT_SPRITE_DATA_DIR`. The `data/` directory is Git-ignored.

## Project resources

- [ChatGPT plugin template and skill instructions](plugin/README.md)
- [Roadmap](ROADMAP.md) · [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)
- [Issues](https://github.com/mplsjohnnycage/langextract-sprite/issues) · [Releases](https://github.com/mplsjohnnycage/langextract-sprite/releases)
- [Upstream Google LangExtract](https://github.com/google/langextract)

**License:** [Apache 2.0](LICENSE). This project depends on, but does not fork or bundle, Google LangExtract.
