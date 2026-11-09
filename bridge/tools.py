"""Constrained JSON tool protocol for an already-authorized Sprite MCP exec.

This is not an MCP server. The caller runs `python -m bridge.tools` via the
existing Sprites exec tool, passing a JSON request as one command argument.
"""
from __future__ import annotations

import json
import sys
from . import engine

# Fixed allowlist: never interpret tool names as executable commands.
SPECS = {
    "langextract.create": ("Create a durable native LangExtract extraction job", ["document_text", "instructions", "examples"], ["max_char_buffer"]),
    "langextract.next": ("Fetch outstanding native LangExtract prompts", ["job_id"], ["limit"]),
    "langextract.submit": ("Submit an inference client's structured responses", ["job_id", "batch_id", "responses"], []),
    "langextract.list": ("List persisted jobs without source text", [], ["limit"]),
    "langextract.status": ("Read job progress", ["job_id"], []),
    "langextract.result": ("Get aligned extraction result", ["job_id"], []),
    "langextract.audit": ("Audit source and response integrity and spans", ["job_id"], []),
    "langextract.repair": ("Reopen one failed prompt", ["job_id", "prompt_id"], []),
}


def dispatch(request):
    """Return a structured result or error; never run a shell or arbitrary code."""
    try:
        if not isinstance(request, dict) or set(request) != {"tool", "arguments"}:
            raise engine.BridgeError("request requires tool and arguments")
        tool, args = request["tool"], request["arguments"]
        if not isinstance(args, dict):
            raise engine.BridgeError("arguments must be an object")
        if tool == "tools.list":
            if args:
                raise engine.BridgeError("tools.list accepts no arguments")
            return {"ok": True, "tools": [{"name": name, "description": desc,
                    "required": required, "optional": optional}
                    for name, (desc, required, optional) in SPECS.items()]}
        if tool not in SPECS:
            raise engine.BridgeError("unknown tool")
        _, required, optional = SPECS[tool]
        missing = set(required) - set(args)
        unexpected = set(args) - set(required) - set(optional)
        if missing or unexpected:
            raise engine.BridgeError(f"invalid arguments; missing={sorted(missing)}, unexpected={sorted(unexpected)}")
        if tool == "langextract.create":
            result = engine.create_job(args)
        elif tool == "langextract.next":
            result = engine.next_batch(args["job_id"], args.get("limit", 3))
        elif tool == "langextract.submit":
            result = engine.submit_batch(args["job_id"], args["batch_id"], args["responses"])
        elif tool == "langextract.list":
            result = engine.list_jobs(args.get("limit", 20))
        elif tool == "langextract.status":
            result = engine.get_status(args["job_id"])
        elif tool == "langextract.result":
            result = engine.get_result(args["job_id"])
        elif tool == "langextract.audit":
            result = engine.audit_job(args["job_id"])
        else:
            result = engine.reset_prompt(args["job_id"], args["prompt_id"])
        return {"ok": True, "result": result}
    except (engine.BridgeError, ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": str(exc), "type": type(exc).__name__}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(json.dumps({"ok": False, "error": "provide exactly one JSON request argument"}))
        return 2
    try:
        request = json.loads(args[0])
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "error": "invalid request JSON"}))
        return 2
    output = dispatch(request)
    print(json.dumps(output, ensure_ascii=False))
    return 0 if output["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
