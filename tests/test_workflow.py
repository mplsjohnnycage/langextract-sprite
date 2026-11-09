"""Deterministic gateway integration and fail-closed checks."""
import argparse
import importlib.util
import json
from pathlib import Path

import pytest
from bridge import engine

MODULE = Path(__file__).resolve().parents[1] / 'plugin' / 'scripts' / 'workflow.py'
spec = importlib.util.spec_from_file_location('plugin_workflow', MODULE)
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)

EXAMPLES = [{'text': 'Eve joined Zeta.', 'extractions': [
    {'extraction_class': 'person', 'extraction_text': 'Eve'},
    {'extraction_class': 'organization', 'extraction_text': 'Zeta'}]}]


def args(action, **kwargs):
    return argparse.Namespace(command=action, **kwargs)


def write_payload(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(obj), encoding='utf-8')
    path.chmod(0o600)
    return path


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, 'DB', tmp_path / 'jobs.sqlite3')
    monkeypatch.setattr(engine, 'DATA', tmp_path)
    return tmp_path / 'inputs'


def create(inputs):
    file = write_payload(inputs / 'source.json', {
        'document_text': 'Alice joined Acme.',
        'instructions': 'Extract literal people and organizations.',
        'examples': EXAMPLES,
    })
    return workflow.execute(args('start', file=file))['job_id']


def test_doctor_enforces_exact_catalog():
    result = workflow.execute(args('doctor'))
    assert result['ready'] and len(result['operations']) == 8
    assert result['inference'] == 'active_chatgpt_only'


def test_active_inference_gate_and_verified_completion(inputs):
    job_id = create(inputs)
    with pytest.raises(engine.BridgeError, match='not completed'):
        workflow.execute(args('finish', job_id=job_id))
    step = workflow.execute(args('resume', job_id=job_id, limit=3))
    assert step['model_action_required'] is True
    batch = step['batch']
    assert batch['prompts']
    response = {'extractions': [{'person': 'Alice'}, {'organization': 'Acme'}]}
    file = write_payload(inputs / 'answer.json', {
        'batch_id': batch['batch_id'],
        'responses': [{'prompt_id': batch['prompts'][0]['prompt_id'],
                       'response_text': json.dumps(response)}],
    })
    assert workflow.execute(args('submit', job_id=job_id, file=file))['state'] == 'completed'
    result = workflow.execute(args('finish', job_id=job_id))
    assert result['completion_verified'] is True
    assert result['audit']['ok'] is True
    assert len(result['result']['verified_extractions']) == 2
    assert workflow.execute(args('resume', job_id=job_id, limit=3))['completion_verified'] is True


def test_reject_unprotected_input_and_invalid_shape(inputs, tmp_path):
    outside = write_payload(tmp_path / 'outside.json', {})
    with pytest.raises(engine.BridgeError, match='data/inputs'):
        workflow.execute(args('start', file=outside))
    nested = write_payload(inputs / 'not-object.json', [])
    with pytest.raises(engine.BridgeError, match='JSON object'):
        workflow.execute(args('start', file=nested))


def test_wrong_batch_rejected_without_advancing(inputs):
    job_id = create(inputs)
    batch = workflow.execute(args('next', job_id=job_id, limit=3))['batch']
    file = write_payload(inputs / 'wrong-batch.json', {
        'batch_id': 'not-a-real-batch',
        'responses': [{'prompt_id': batch['prompts'][0]['prompt_id'],
                       'response_text': '{"extractions":[]}'}],
    })
    with pytest.raises(engine.BridgeError, match='batch IDs'):
        workflow.execute(args('submit', job_id=job_id, file=file))
    assert engine.get_status(job_id)['pending'] == 1


def test_finish_fails_closed_on_forged_audit(inputs, monkeypatch):
    job_id = create(inputs)
    batch = workflow.execute(args('next', job_id=job_id, limit=3))['batch']
    file = write_payload(inputs / 'answer.json', {
        'batch_id': batch['batch_id'],
        'responses': [{'prompt_id': batch['prompts'][0]['prompt_id'],
                       'response_text': '{"extractions":[{"person":"Alice"}]}'}],
    })
    workflow.execute(args('submit', job_id=job_id, file=file))
    monkeypatch.setattr(engine, 'audit_job', lambda _id: {
        'ok': False, 'state': 'completed', 'issues': ['deliberate test failure'],
        'verified_spans_checked': 1, 'responses_checked': 1,
    })
    with pytest.raises(engine.BridgeError, match='audit failure'):
        workflow.execute(args('finish', job_id=job_id))


def test_finish_fails_closed_on_unverified_extractions(inputs, monkeypatch):
    job_id = create(inputs)
    batch = workflow.execute(args('next', job_id=job_id, limit=3))['batch']
    file = write_payload(inputs / 'answer.json', {
        'batch_id': batch['batch_id'],
        'responses': [{'prompt_id': batch['prompts'][0]['prompt_id'],
                       'response_text': '{"extractions":[{"person":"Alice"}]}'}],
    })
    workflow.execute(args('submit', job_id=job_id, file=file))
    original = engine.get_result
    def tampered(_id):
        x = original(_id)
        x['result']['unverified_extractions'] = [{'text':'not found'}]
        return x
    monkeypatch.setattr(engine, 'get_result', tampered)
    with pytest.raises(engine.BridgeError, match='unverified'):
        workflow.execute(args('finish', job_id=job_id))
