"""Durable ChatGPT-in-the-loop LangExtract engine (no remote model API)."""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

import langextract as lx
from langextract.core.base_model import BaseLanguageModel
from langextract.core.types import ScoredOutput

ROOT = Path(__file__).resolve().parents[1]
# Keep legacy source-checkout storage on the Sprite, but support installed wheels
# and an explicit per-deployment state directory without writing to site-packages.
_default_data = (ROOT / "data" if (ROOT / "pyproject.toml").exists()
                 else Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
                 / "langextract-sprite")
DATA = Path(os.environ.get("LANGEXTRACT_SPRITE_DATA_DIR", _default_data)).expanduser().resolve()
DB = DATA / "jobs.sqlite3"
MAX_DOC_CHARS = 250_000
MAX_PROMPT_BATCH = 8


class BridgeError(Exception):
    pass


def connect(db_path: Path | None = None):
    p = db_path or DB
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(p.parent, 0o700)
    con = sqlite3.connect(str(p), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, text TEXT NOT NULL, text_sha256 TEXT NOT NULL,
            instructions TEXT NOT NULL, examples_json TEXT NOT NULL,
            max_chars INTEGER NOT NULL, state TEXT NOT NULL,
            result_json TEXT, error TEXT, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prompts(
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
            ordinal INTEGER NOT NULL, text TEXT NOT NULL,
            response TEXT, response_sha256 TEXT,
            UNIQUE(job_id, ordinal)
        );
    """)
    if p.exists():
        os.chmod(p, 0o600)
    return con


def make_examples(value):
    if not isinstance(value, list) or not value:
        raise BridgeError("examples must be a nonempty list of {text, extractions}")
    converted = []
    for example in value:
        if not isinstance(example, dict) or not isinstance(example.get("text"), str):
            raise BridgeError("each example needs text")
        extractions = example.get("extractions")
        if not isinstance(extractions, list):
            raise BridgeError("each example needs an extractions list")
        es = []
        for e in extractions:
            if (not isinstance(e, dict) or not isinstance(e.get("extraction_class"), str)
                    or not isinstance(e.get("extraction_text"), str)):
                raise BridgeError("extractions need extraction_class and extraction_text")
            es.append(lx.data.Extraction(
                extraction_class=e["extraction_class"],
                extraction_text=e["extraction_text"],
                attributes=e.get("attributes")
            ))
        converted.append(lx.data.ExampleData(text=example["text"], extractions=es))
    return converted


class CaptureModel(BaseLanguageModel):
    def __init__(self):
        super().__init__()
        self.prompts: list[str] = []

    def infer(self, batch_prompts, **kwargs):
        for prompt in batch_prompts:
            self.prompts.append(prompt)
            yield [ScoredOutput(output='{"extractions":[]}')]


class ReplayModel(BaseLanguageModel):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows
        self.pos = 0

    def infer(self, batch_prompts, **kwargs):
        for prompt in batch_prompts:
            if self.pos >= len(self.rows):
                raise BridgeError("LangExtract generated more prompts than prepared")
            row = self.rows[self.pos]
            if row["text"] != prompt:
                raise BridgeError(f"LangExtract prompt drift at ordinal {self.pos}")
            self.pos += 1
            yield [ScoredOutput(output=row["response"])]


def native_extract(text, instructions, examples, max_chars, model):
    return lx.extract(
        text, prompt_description=instructions,
        examples=make_examples(examples), model=model,
        max_char_buffer=max_chars, batch_length=1, max_workers=1,
        fence_output=False, use_schema_constraints=False,
        show_progress=False, resolver_params={"suppress_parse_errors": False},
    )


def create_job(payload, db_path=None):
    text = payload.get("document_text")
    instructions = payload.get("instructions")
    examples = payload.get("examples")
    max_chars = payload.get("max_char_buffer", 1000)
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_DOC_CHARS:
        raise BridgeError(f"document_text must contain 1-{MAX_DOC_CHARS} characters")
    if not isinstance(instructions, str) or not instructions.strip():
        raise BridgeError("instructions must be a nonempty string")
    if not isinstance(max_chars, int) or not 64 <= max_chars <= 10000:
        raise BridgeError("max_char_buffer must be 64-10000")
    make_examples(examples)
    capture = CaptureModel()
    native_extract(text, instructions, examples, max_chars, capture)
    if not capture.prompts:
        raise BridgeError("LangExtract created no inference prompts")
    jid = uuid.uuid4().hex
    with connect(db_path) as con:
        con.execute(
            "INSERT INTO jobs(id,text,text_sha256,instructions,examples_json,max_chars,state,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (jid,text,hashlib.sha256(text.encode()).hexdigest(),instructions,
             json.dumps(examples,ensure_ascii=False),max_chars,"awaiting_model",int(time.time()))
        )
        con.executemany(
            "INSERT INTO prompts(id,job_id,ordinal,text) VALUES(?,?,?,?)",
            [(uuid.uuid4().hex,jid,i,p) for i,p in enumerate(capture.prompts)]
        )
    return {"job_id":jid,"state":"awaiting_model","prompt_count":len(capture.prompts),
            "source_sha256":hashlib.sha256(text.encode()).hexdigest()}


def batch_key(job_id, prompt_ids):
    return hashlib.sha256((job_id+":"+":".join(prompt_ids)).encode()).hexdigest()[:20]


def next_batch(job_id, limit=3, db_path=None):
    if not isinstance(limit,int) or not 1 <= limit <= MAX_PROMPT_BATCH:
        raise BridgeError(f"limit must be 1-{MAX_PROMPT_BATCH}")
    with connect(db_path) as con:
        job = con.execute("SELECT id,state FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not job: raise BridgeError("unknown job_id")
        rows = con.execute("SELECT id,ordinal,text FROM prompts WHERE job_id=? AND response IS NULL ORDER BY ordinal LIMIT ?",(job_id,limit)).fetchall()
        return {"job_id":job_id,"state":job["state"],
                "batch_id":batch_key(job_id,[r["id"] for r in rows]) if rows else None,
                "prompts":[{"prompt_id":r["id"],"ordinal":r["ordinal"],"prompt_text":r["text"]} for r in rows]}


def validate_response(raw):
    if not isinstance(raw,str):raise BridgeError("response_text must be a JSON string")
    try: obj=json.loads(raw)
    except json.JSONDecodeError as e: raise BridgeError(f"response_text invalid JSON: {e.msg}") from e
    if not isinstance(obj,dict) or not isinstance(obj.get("extractions"),list):
        raise BridgeError("response_text must be a JSON object with extractions array")
    for e in obj["extractions"]:
        if not isinstance(e,dict) or not e:
            raise BridgeError("each extraction must be a nonempty JSON object")
        vals = [(k,v) for k,v in e.items() if not k.endswith("_attributes")]
        if len(vals)!=1 or not isinstance(vals[0][1],str):
            raise BridgeError("each extraction needs exactly one class key and string span")
        for key, value in e.items():
            if key.endswith("_attributes") and value is not None and not isinstance(value, dict):
                raise BridgeError(f"{key} attributes must be a JSON object or null")
    return raw


def submit_batch(job_id, batch_id, responses, db_path=None):
    if not isinstance(responses,list) or not responses or len(responses)>MAX_PROMPT_BATCH:
        raise BridgeError("responses must be a nonempty list, up to batch limit")
    ids = [r.get("prompt_id") for r in responses if isinstance(r,dict)]
    if len(ids)!=len(responses) or len(ids)!=len(set(ids)):
        raise BridgeError("responses need unique prompt_id")
    with connect(db_path) as con:
        job=con.execute("SELECT state FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not job:raise BridgeError("unknown job_id")
        if job["state"] not in ("awaiting_model","completed"):
            raise BridgeError(f"job in state {job['state']}")
        rows=con.execute("SELECT id,ordinal,response FROM prompts WHERE job_id=?",(job_id,)).fetchall()
        known={r["id"]:r for r in rows}
        if not all(i in known for i in ids):raise BridgeError("prompt does not belong to job")
        ordered=sorted(ids,key=lambda x:known[x]["ordinal"])
        if batch_id!=batch_key(job_id,ordered):raise BridgeError("batch_id mismatch")
        submitted={r["prompt_id"]:validate_response(r["response_text"]) for r in responses}
        accepted=0
        for pid in ordered:
            old=known[pid]["response"]
            raw=submitted[pid]
            if old is not None:
                if old!=raw:raise BridgeError("conflicting response re-submission")
            else:accepted+=1
        for pid in ordered:
            raw=submitted[pid]
            con.execute("UPDATE prompts SET response=?,response_sha256=? WHERE id=? AND response IS NULL",
                        (raw,hashlib.sha256(raw.encode()).hexdigest(),pid))
        count=con.execute("SELECT COUNT(*) FROM prompts WHERE job_id=? AND response IS NULL",(job_id,)).fetchone()[0]
    if count==0 and job["state"]!="completed":
        try:
            finalize(job_id,db_path=db_path)
        except Exception:
            # Native extraction errors are persisted as failed for an
            # operator to repair. Unexpected preflight/storage errors still
            # propagate rather than claiming a completed job.
            if get_status(job_id,db_path=db_path)["state"]!="failed":
                raise
    status=get_status(job_id,db_path=db_path)
    return {"job_id":job_id,"accepted":accepted,"idempotent":accepted==0,
            "remaining":status["pending"],"state":status["state"],"error":status["error"]}


def finalize(job_id,db_path=None):
    with connect(db_path) as con:
        job=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
        rows=con.execute("SELECT * FROM prompts WHERE job_id=? ORDER BY ordinal",(job_id,)).fetchall()
        if not job or not rows:raise BridgeError("job not prepared")
        if any(r["response"] is None for r in rows):
            raise BridgeError("job still has pending prompts")
        text=job["text"]
        if hashlib.sha256(text.encode()).hexdigest()!=job["text_sha256"]:
            raise BridgeError("source text hash mismatch")
        try:
            model=ReplayModel(rows)
            doc=native_extract(text,job["instructions"],json.loads(job["examples_json"]),job["max_chars"],model)
            if model.pos!=len(rows):raise BridgeError("LangExtract used fewer prompts than prepared")
            verified,rejected=[],[]
            for e in doc.extractions or []:
                interval=e.char_interval
                start=getattr(interval,"start_pos",None)
                end=getattr(interval,"end_pos",None)
                record={"class":e.extraction_class,"text":e.extraction_text,
                        "start":start,"end":end,"attributes":e.attributes or {},
                        "alignment_status":str(e.alignment_status)}
                if isinstance(start,int) and isinstance(end,int) and text[start:end]==e.extraction_text:
                    verified.append(record)
                else:rejected.append({**record,"reason":"source span mismatch or unaligned"})
            result={"job_id":job_id,"source_sha256":job["text_sha256"],
                    "native_engine":"langextract","prompt_count":len(rows),
                    "verified_extractions":verified,"unverified_extractions":rejected}
            con.execute("UPDATE jobs SET state='completed',result_json=?,error=NULL WHERE id=?",
                        (json.dumps(result,ensure_ascii=False),job_id))
        except Exception as e:
            con.execute("UPDATE jobs SET state='failed',error=? WHERE id=?",
                        (f"{type(e).__name__}: {str(e)[:400]}",job_id))
            # Explicitly commit failure state before re-raising. Otherwise
            # sqlite's context manager rolls back the failure marker.
            con.commit()
            raise


def get_status(job_id,db_path=None):
    with connect(db_path) as con:
        job=con.execute("SELECT id,state,error,text_sha256,created_at FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not job: raise BridgeError("unknown job_id")
        all_n=con.execute("SELECT COUNT(*) FROM prompts WHERE job_id=?",(job_id,)).fetchone()[0]
        done=con.execute("SELECT COUNT(*) FROM prompts WHERE job_id=? AND response IS NOT NULL",(job_id,)).fetchone()[0]
        return {"job_id":job_id,"state":job["state"],"error":job["error"],"source_sha256":job["text_sha256"],
                "total":all_n,"submitted":done,"pending":all_n-done,"created_at":job["created_at"]}


def get_result(job_id,db_path=None):
    with connect(db_path) as con:
        job=con.execute("SELECT state,result_json,error FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not job:raise BridgeError("unknown job_id")
        if job["state"]!="completed":
            return {"job_id":job_id,"state":job["state"],"error":job["error"],"result":None}
        return {"job_id":job_id,"state":"completed","result":json.loads(job["result_json"])}


def reset_prompt(job_id,prompt_id,db_path=None):
    with connect(db_path) as con:
        job=con.execute("SELECT state FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not job or job["state"]!="failed":
            raise BridgeError("repair allowed only for failed jobs")
        if con.execute("SELECT COUNT(*) FROM prompts WHERE job_id=? AND id=?",(job_id,prompt_id)).fetchone()[0]!=1:
            raise BridgeError("unknown prompt_id")
        con.execute("UPDATE prompts SET response=NULL,response_sha256=NULL WHERE id=?",(prompt_id,))
        con.execute("UPDATE jobs SET state='awaiting_model',error=NULL WHERE id=?",(job_id,))
    return get_status(job_id,db_path=db_path)



def list_jobs(limit=20, db_path=None):
    """List durable jobs for restart/recovery without returning source text."""
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise BridgeError("limit must be 1-100")
    with connect(db_path) as con:
        rows = con.execute("""
            SELECT j.id, j.state, j.created_at, COUNT(p.id) AS total,
                   SUM(CASE WHEN p.response IS NULL THEN 1 ELSE 0 END) AS pending
            FROM jobs AS j LEFT JOIN prompts AS p ON p.job_id = j.id
            GROUP BY j.id ORDER BY j.created_at DESC, j.id DESC LIMIT ?
        """, (limit,)).fetchall()
    return {"jobs": [{"job_id": r["id"], "state": r["state"],
                       "created_at": r["created_at"], "total": r["total"],
                       "pending": r["pending"]} for r in rows]}


def audit_job(job_id, db_path=None):
    """Read-only verification of persisted content and LangExtract source spans.

    This proves integrity and exact text alignment, not real-world truth of claims.
    """
    with connect(db_path) as con:
        job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise BridgeError("unknown job_id")
        prompts = con.execute(
            "SELECT id,ordinal,response,response_sha256 FROM prompts "
            "WHERE job_id=? ORDER BY ordinal", (job_id,)
        ).fetchall()

    issues = []
    if hashlib.sha256(job["text"].encode()).hexdigest() != job["text_sha256"]:
        issues.append("source SHA-256 mismatch")
    responses_checked = 0
    for r in prompts:
        if r["response"] is None:
            if r["response_sha256"] is not None:
                issues.append(f"orphaned response SHA-256 at ordinal {r['ordinal']}")
            if job["state"] == "completed":
                issues.append(f"missing response at ordinal {r['ordinal']}")
            continue
        responses_checked += 1
        if hashlib.sha256(r["response"].encode()).hexdigest() != r["response_sha256"]:
            issues.append(f"response SHA-256 mismatch at ordinal {r['ordinal']}")

    spans_checked = 0
    if job["state"] == "completed":
        try:
            result = json.loads(job["result_json"])
            if result["source_sha256"] != job["text_sha256"]:
                issues.append("result source SHA-256 mismatch")
            if result["prompt_count"] != len(prompts):
                issues.append("result prompt count mismatch")
            if result["native_engine"] != "langextract":
                issues.append("result engine mismatch")
            for index, extraction in enumerate(result["verified_extractions"]):
                start, end = extraction["start"], extraction["end"]
                if (not isinstance(start, int) or not isinstance(end, int)
                    or start < 0 or start >= end or end > len(job["text"])
                    or job["text"][start:end] != extraction["text"]):
                    issues.append(f"source span mismatch at extraction {index}")
                else:
                    spans_checked += 1
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            issues.append("completed result malformed or unavailable")

    return {"job_id": job_id, "state": job["state"], "ok": not issues,
            "total_prompts": len(prompts), "responses_checked": responses_checked,
            "verified_spans_checked": spans_checked, "issues": issues}
