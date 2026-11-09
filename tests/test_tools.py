import json
import pytest
from bridge import engine
from bridge import tools as tool_api

EXAMPLES = [{"text": "Eve joined Zeta.", "extractions": [
    {"extraction_class": "person", "extraction_text": "Eve"},
    {"extraction_class": "organization", "extraction_text": "Zeta"}]}]


def test_tool_catalog_and_one_call_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB", tmp_path / "jobs.sqlite3")
    catalog = tool_api.dispatch({"tool": "tools.list", "arguments": {}})
    names = {item["name"] for item in catalog["tools"]}
    assert {"langextract.create", "langextract.next", "langextract.submit",
            "langextract.list", "langextract.status", "langextract.result",
            "langextract.audit", "langextract.repair"}.issubset(names)
    created = tool_api.dispatch({"tool": "langextract.create", "arguments": {
        "document_text": "Alice joined Acme.",
        "instructions": "Extract exact entities.", "examples": EXAMPLES}})
    assert created["ok"] is True
    job_id = created["result"]["job_id"]
    batch = tool_api.dispatch({"tool": "langextract.next", "arguments": {"job_id": job_id}})["result"]
    response = {"extractions": [{"person": "Alice"}, {"organization": "Acme"}]}
    submitted = tool_api.dispatch({"tool": "langextract.submit", "arguments": {
        "job_id": job_id, "batch_id": batch["batch_id"],
        "responses": [{"prompt_id": batch["prompts"][0]["prompt_id"],
                       "response_text": json.dumps(response)}]}})
    assert submitted["result"]["state"] == "completed"
    assert tool_api.dispatch({"tool": "langextract.audit", "arguments": {"job_id": job_id}})["result"]["ok"]
    assert tool_api.dispatch({"tool": "langextract.result", "arguments": {"job_id": job_id}})["result"]["state"] == "completed"


def test_tool_dispatch_rejects_unexpected_inputs_without_code_execution():
    assert tool_api.dispatch({"tool": "not.allowed", "arguments": {}})["ok"] is False
    assert tool_api.dispatch({"tool": "langextract.list", "arguments": {"unexpected": 3}})["ok"] is False
    assert tool_api.dispatch({"tool": "langextract.create", "arguments": {"document_text": "x"}})["ok"] is False
    assert tool_api.dispatch({"tool": "langextract.next", "arguments": {"job_id": "unknown"}})["ok"] is False
