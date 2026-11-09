#!/usr/bin/env python3
"""Fail-closed LangExtract Sprite lifecycle gates (no model calls)."""
from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
import sys

from bridge import engine
from bridge import tools as dispatcher

REQUIRED = frozenset({
    'langextract.create', 'langextract.next', 'langextract.submit',
    'langextract.list', 'langextract.status', 'langextract.result',
    'langextract.audit', 'langextract.repair',
})


def protected_json_file(file):
    """Read a protected local JSON payload without leaking source in argv."""
    path = Path(file).expanduser().resolve()
    inputs = (engine.DATA / 'inputs').resolve()
    if not path.is_relative_to(inputs):
        raise engine.BridgeError('file must be inside the configured data/inputs directory')
    if not path.is_file():
        raise engine.BridgeError('input file not found')
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise engine.BridgeError('input file permissions must deny group/other access (0600)')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise engine.BridgeError('payload must be a JSON object')
    return value


def verified_result(job_id):
    status = engine.get_status(job_id)
    if status['state'] != 'completed' or status['pending'] != 0:
        raise engine.BridgeError('final verification blocked: job not completed')
    result = engine.get_result(job_id)
    audit = engine.audit_job(job_id)
    if result['state'] != 'completed' or not isinstance(result.get('result'), dict):
        raise engine.BridgeError('final verification blocked: result unavailable')
    doc = result['result']
    if not audit['ok'] or audit['state'] != 'completed' or audit['issues']:
        raise engine.BridgeError('final verification blocked: audit failure')
    if doc.get('source_sha256') != status['source_sha256']:
        raise engine.BridgeError('final verification blocked: source hash mismatch')
    if doc.get('unverified_extractions'):
        raise engine.BridgeError('final verification blocked: unverified extractions exist')
    if len(doc.get('verified_extractions', [])) != audit['verified_spans_checked']:
        raise engine.BridgeError('final verification blocked: span count mismatch')
    if audit['responses_checked'] != status['total']:
        raise engine.BridgeError('final verification blocked: response count mismatch')
    return {'status': status, 'result': doc, 'audit': audit,
            'completion_verified': True}


def execute(args):
    cmd = args.command
    if cmd == 'doctor':
        catalog = dispatcher.dispatch({'tool': 'tools.list', 'arguments': {}})
        if not catalog['ok'] or {x['name'] for x in catalog['tools']} != REQUIRED:
            raise engine.BridgeError('doctor failed: dispatcher operations mismatch')
        return {'operations': sorted(REQUIRED), 'inference': 'active_chatgpt_only',
                'ready': True}
    if cmd == 'start':
        return engine.create_job(protected_json_file(args.file))
    if cmd == 'list':
        return engine.list_jobs(args.limit)
    if cmd == 'repair':
        return engine.reset_prompt(args.job_id, args.prompt_id)
    if cmd == 'finish':
        return verified_result(args.job_id)
    if cmd == 'submit':
        status = engine.get_status(args.job_id)
        if status['state'] != 'awaiting_model':
            raise engine.BridgeError('submit blocked: job is not awaiting_model')
        payload = protected_json_file(args.file)
        if not isinstance(payload, dict) or set(payload) != {'batch_id', 'responses'}:
            raise engine.BridgeError('submission requires exactly batch_id and responses')
        if not isinstance(payload['responses'], list) or not payload['responses']:
            raise engine.BridgeError('submission requires responses')
        pending = engine.next_batch(args.job_id, len(payload['responses']))
        # Accept only the pending contiguous batch, not arbitrary/old prompts.
        if (payload['batch_id'] != pending['batch_id'] or
            {r.get('prompt_id') for r in payload['responses'] if isinstance(r, dict)}
            != {p['prompt_id'] for p in pending['prompts']} or
            len(payload['responses']) != len(pending['prompts'])):
            raise engine.BridgeError('submission blocked: batch IDs or prompt IDs mismatch')
        submitted = engine.submit_batch(args.job_id, payload['batch_id'], payload['responses'])
        if submitted['state'] == 'failed':
            raise engine.BridgeError('submission saved but native finalization failed; inspect status and repair')
        return submitted
    if cmd in ('next', 'resume'):
        status = engine.get_status(args.job_id)
        if status['state'] == 'completed':
            return verified_result(args.job_id)
        if status['state'] == 'failed':
            raise engine.BridgeError('job failed: inspect status/error and repair a prompt')
        if status['state'] != 'awaiting_model' or status['pending'] <= 0:
            raise engine.BridgeError('no prompts available in a valid awaiting_model state')
        batch = engine.next_batch(args.job_id, args.limit)
        if not batch['prompts'] or not batch['batch_id']:
            raise engine.BridgeError('next returned no prompts despite pending work')
        return {'status': status, 'batch': batch, 'model_action_required': True}
    raise engine.BridgeError('unsupported action')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Deterministic LangExtract Sprite lifecycle gates; no LLM API calls')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    start = sub.add_parser('start'); start.add_argument('--file', required=True)
    listing = sub.add_parser('list'); listing.add_argument('--limit', type=int, default=20)
    for action in ('next', 'resume'):
        command = sub.add_parser(action)
        command.add_argument('--job-id', required=True)
        command.add_argument('--limit', type=int, default=3)
    submit = sub.add_parser('submit'); submit.add_argument('--job-id', required=True); submit.add_argument('--file', required=True)
    finish = sub.add_parser('finish'); finish.add_argument('--job-id', required=True)
    repair = sub.add_parser('repair'); repair.add_argument('--job-id', required=True); repair.add_argument('--prompt-id', required=True)
    args = parser.parse_args(argv)
    try:
        result = execute(args)
        print(json.dumps({'ok': True, 'action': args.command, 'data': result}, ensure_ascii=False))
        return 0
    except (engine.BridgeError, ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'ok': False, 'action': args.command, 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
