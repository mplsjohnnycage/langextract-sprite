import json
import pytest
from bridge import engine as e

EXAMPLES=[{"text":"Eve joined Zeta in May 2024.","extractions":[
    {"extraction_class":"person","extraction_text":"Eve"},
    {"extraction_class":"organization","extraction_text":"Zeta"},
    {"extraction_class":"date","extraction_text":"May 2024"}]}]
SOURCE="Alice joined Acme in March 2025."

def new(payload,db):
    return e.create_job({"document_text":SOURCE,"instructions":"Extract entities using exact source spans.","examples":EXAMPLES,**(payload or {})},db)

def response(*entities):
    return json.dumps({"extractions":[{k:v} for k,v in entities]})

def test_native_alignment_replay_and_durable_restart(tmp_path):
    db=tmp_path/"db.sqlite"
    j=new({},db); assert j["prompt_count"]==1
    b=e.next_batch(j["job_id"],db_path=db)
    raw=response(("person","Alice"),("organization","Acme"),("date","March 2025"))
    p={"prompt_id":b["prompts"][0]["prompt_id"],"response_text":raw}
    done=e.submit_batch(j["job_id"],b["batch_id"],[p],db)
    assert done["state"]=="completed"
    assert e.get_status(j["job_id"],db)["pending"]==0
    result=e.get_result(j["job_id"],db)["result"]
    assert result["native_engine"]=="langextract"
    assert [(x["text"],x["start"],x["end"]) for x in result["verified_extractions"]]==[
        ("Alice",0,5),("Acme",13,17),("March 2025",21,31)]
    assert not result["unverified_extractions"]
    assert e.submit_batch(j["job_id"],b["batch_id"],[p],db)["idempotent"]
    with pytest.raises(e.BridgeError,match="conflicting"):
        e.submit_batch(j["job_id"],b["batch_id"],[{**p,"response_text":response(("person","Eve"))}],db)
    assert e.get_result(j["job_id"],db)["result"]==result

def test_invalid_response_is_atomic_and_retryable(tmp_path):
    db=tmp_path/"test.sqlite";j=new({},db);b=e.next_batch(j["job_id"],db_path=db)
    p=b["prompts"][0]["prompt_id"]
    for raw in ["not json","{}",'{"extractions":[{"person":13}]}']:
        with pytest.raises(e.BridgeError):
            e.submit_batch(j["job_id"],b["batch_id"],[{"prompt_id":p,"response_text":raw}],db)
    assert e.get_status(j["job_id"],db)["pending"]==1
    with pytest.raises(e.BridgeError,match="batch_id mismatch"):
        e.submit_batch(j["job_id"],"wrong",[{"prompt_id":p,"response_text":response()}],db)

def test_multi_chunk_out_of_order_and_job_isolation(tmp_path):
    db=tmp_path/"test.sqlite"
    text=" ".join([f"Person{i} joined Company{i} in 2025." for i in range(22)])
    j=new({"document_text":text,"max_char_buffer":100},db)
    assert j["prompt_count"]>1
    other=new({},db)
    prompts=[]
    while len(prompts)<j["prompt_count"]:
        batch=e.next_batch(j["job_id"],limit=8,db_path=db)
        for p in batch["prompts"]:
            if p["prompt_id"] not in {q["prompt_id"] for q in prompts}: prompts.append(p)
        if len(prompts)<j["prompt_count"]:
            # collect all through database since next is intentionally an unclaimed, retryable queue
            with e.connect(db) as c:
                prompts=[dict(x) for x in c.execute("SELECT id AS prompt_id,ordinal,text AS prompt_text FROM prompts WHERE job_id=? ORDER BY ordinal",(j["job_id"],)).fetchall()]
    assert len(prompts)==j["prompt_count"]
    with pytest.raises(e.BridgeError,match="does not belong"):
        e.submit_batch(j["job_id"],e.batch_key(j["job_id"],[e.next_batch(other["job_id"],db_path=db)["prompts"][0]["prompt_id"]]),
                       [{"prompt_id":e.next_batch(other["job_id"],db_path=db)["prompts"][0]["prompt_id"],"response_text":response()}],db)
    # submit from the end, proving independent chunks can be returned out of order
    for p in reversed(prompts):
        bid=e.batch_key(j["job_id"],[p["prompt_id"]])
        s=e.submit_batch(j["job_id"],bid,[{"prompt_id":p["prompt_id"],"response_text":response()}],db)
    assert s["state"]=="completed"
    assert e.get_result(j["job_id"],db)["result"]["prompt_count"]==j["prompt_count"]

def test_rejected_not_provenance(tmp_path):
    db=tmp_path/"test.sqlite"
    j=new({},db);b=e.next_batch(j["job_id"],db_path=db)
    p=b["prompts"][0]["prompt_id"]
    e.submit_batch(j["job_id"],b["batch_id"],
      [{"prompt_id":p,"response_text":response(("person","PersonNotInText"))}],db)
    result=e.get_result(j["job_id"],db)["result"]
    assert result["verified_extractions"]==[]

def test_input_contracts(tmp_path):
    db=tmp_path/"test.sqlite"
    with pytest.raises(e.BridgeError,match="examples"):
        new({"examples":[]},db)
    with pytest.raises(e.BridgeError,match="max_char_buffer"):
        new({"max_char_buffer":20},db)
    with pytest.raises(e.BridgeError,match="document_text"):
        new({"document_text":""},db)


def test_failed_native_finalization_persists_then_repairs(tmp_path, monkeypatch):
    db=tmp_path/"failed.sqlite"
    j=new({},db)
    b=e.next_batch(j["job_id"],db_path=db)
    prompt=b["prompts"][0]["prompt_id"]
    raw=response(("person","Alice"))
    orig=e.native_extract

    def injected(text,instructions,examples,max_chars,model):
        if isinstance(model,e.ReplayModel):
            raise RuntimeError("simulated native parse failure")
        return orig(text,instructions,examples,max_chars,model)

    monkeypatch.setattr(e,"native_extract",injected)
    result=e.submit_batch(j["job_id"],b["batch_id"],
                          [{"prompt_id":prompt,"response_text":raw}],db)
    assert result["state"]=="failed"
    assert "simulated native parse failure" in result["error"]
    assert e.get_status(j["job_id"],db)["state"]=="failed"
    assert e.get_result(j["job_id"],db)["result"] is None
    reopened=e.reset_prompt(j["job_id"],prompt,db)
    assert reopened["state"]=="awaiting_model" and reopened["pending"]==1
    monkeypatch.setattr(e,"native_extract",orig)
    b2=e.next_batch(j["job_id"],db_path=db)
    assert b2["prompts"][0]["prompt_id"]==prompt
    repaired=e.submit_batch(j["job_id"],b2["batch_id"],
                            [{"prompt_id":prompt,"response_text":raw}],db)
    assert repaired["state"]=="completed"
    assert e.get_result(j["job_id"],db)["result"]["verified_extractions"][0]["text"]=="Alice"


def test_malformed_attributes_rejected_atomically_before_native_parse(tmp_path):
    db = tmp_path / "attributes.sqlite"
    job = new({}, db)
    batch = e.next_batch(job["job_id"], db_path=db)
    prompt_id = batch["prompts"][0]["prompt_id"]
    for invalid_attributes in ("not-a-dict", [1, 2], 42):
        raw = json.dumps({"extractions": [
            {"person": "Alice", "person_attributes": invalid_attributes}
        ]})
        with pytest.raises(e.BridgeError, match="attributes"):
            e.submit_batch(job["job_id"], batch["batch_id"], [
                {"prompt_id": prompt_id, "response_text": raw}
            ], db)
        assert e.get_status(job["job_id"], db)["pending"] == 1
    accepted = e.submit_batch(job["job_id"], batch["batch_id"], [
        {"prompt_id": prompt_id, "response_text": json.dumps({
            "extractions": [{"person": "Alice", "person_attributes": {}}]
        })}
    ], db)
    assert accepted["state"] == "completed"


def test_list_jobs_supports_recovery_without_leaking_source(tmp_path):
    db = tmp_path / "jobs.sqlite"
    created = new({}, db)
    pending = e.list_jobs(db_path=db)
    assert pending["jobs"][0]["job_id"] == created["job_id"]
    assert pending["jobs"][0]["state"] == "awaiting_model"
    assert pending["jobs"][0]["pending"] == 1
    assert "document_text" not in json.dumps(pending)
    assert "Alice joined" not in json.dumps(pending)


def test_audit_job_verifies_persisted_source_response_and_spans(tmp_path):
    db = tmp_path / "jobs.sqlite"
    created = new({}, db)
    batch = e.next_batch(created["job_id"], db_path=db)
    raw = response(("person", "Alice"), ("organization", "Acme"))
    e.submit_batch(created["job_id"], batch["batch_id"], [
        {"prompt_id": batch["prompts"][0]["prompt_id"], "response_text": raw}
    ], db)
    report = e.audit_job(created["job_id"], db_path=db)
    assert report["ok"] is True
    assert report["responses_checked"] == 1
    assert report["verified_spans_checked"] == 2
    with e.connect(db) as con:
        con.execute("UPDATE prompts SET response_sha256 = 'tampered' WHERE job_id=?", (created["job_id"],))
    report = e.audit_job(created["job_id"], db_path=db)
    assert report["ok"] is False
    assert any("response SHA-256" in issue for issue in report["issues"])


def test_configured_state_directory_for_public_deployments(tmp_path):
    import os
    import subprocess
    import sys
    env = os.environ.copy()
    env['LANGEXTRACT_SPRITE_DATA_DIR'] = str(tmp_path / 'alternate-state')
    result = subprocess.run([sys.executable, '-c',
        'from bridge import engine; assert str(engine.DATA).endswith("alternate-state"); engine.connect().close(); print(engine.DB)'],
        env=env, capture_output=True, text=True, check=True)
    assert str(tmp_path / 'alternate-state' / 'jobs.sqlite3') in result.stdout
    assert (tmp_path / 'alternate-state' / 'jobs.sqlite3').exists()


def test_input_file_follows_configured_state_root(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from bridge.cli import load_input
    state = tmp_path / 'custom-state'
    input_dir = state / 'inputs'
    input_dir.mkdir(parents=True)
    input_file = input_dir / 'job.json'
    input_file.write_text('{"foo":"bar"}')
    monkeypatch.setattr(e, 'DATA', state)
    assert load_input(SimpleNamespace(data=None, file=str(input_file))) == {'foo': 'bar'}
