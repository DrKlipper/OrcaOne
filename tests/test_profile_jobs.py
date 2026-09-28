import threading
import time
import json

import pytest

from orcaone import operations, profile_jobs
from test_operations import isolated, snorca
from test_profile_api import editor
from conftest import call


def wait_job(instance, job):
    for _ in range(200):
        state = profile_jobs.get(instance, job['job_id'])
        if state['state'] in {'succeeded', 'failed'}:
            return state
        time.sleep(.005)
    raise AssertionError('job did not finish')


def test_progress_duplicate_and_scope():
    release = threading.Event()
    entered = threading.Event()
    def work():
        profile_jobs.report('write', 1, 3)
        entered.set()
        release.wait(2)
        return {'ok': True}
    job = profile_jobs.start('test-one', 'apply', {'plan_id': 'a'}, work)
    try:
        assert entered.wait(1)
        assert profile_jobs.start('test-one', 'apply', {'plan_id': 'a'}, work)['job_id'] == job['job_id']
        assert profile_jobs.get('test-one', job['job_id'])['completed'] == 1
        with pytest.raises(operations.OperationError, match='operation_running'):
            profile_jobs.start('test-one', 'apply', {'plan_id': 'b'}, work)
        with pytest.raises(operations.OperationError, match='operation_not_found'):
            profile_jobs.get('other', job['job_id'])
    finally:
        release.set()
    assert wait_job('test-one', job)['result'] == {'ok': True}
    assert profile_jobs.start('test-one', 'apply', {'plan_id': 'a'}, work)['job_id'] == job['job_id']


def test_failures_are_not_success_and_unknown_exception_is_private():
    def fail():
        raise RuntimeError('secret credential')
    state = wait_job('test-two', profile_jobs.start('test-two', 'apply', {}, fail))
    assert state['state'] == 'failed'
    assert state['error'] == {'error': 'operation_failed'}
    assert 'secret' not in str(state)


def test_known_error_preserves_recovery_information():
    def fail():
        raise operations.OperationError('publish_failed', 500, rolled_back=True)
    state = wait_job('test-three', profile_jobs.start('test-three', 'apply', {}, fail))
    assert state['error'] == {'error': 'publish_failed', 'rolled_back': True}


def test_actual_publish_reports_backup_write_and_verification(snorca, monkeypatch):
    from test_profile_rename_publish import renamed
    from test_profile_publish import preview
    events = []
    monkeypatch.setattr(profile_jobs, 'report', lambda *args: events.append(args))
    selection, _ = renamed(snorca)
    plan = preview(snorca, selection)
    assert not plan['blocked']
    result = operations.apply(snorca.id, plan['id'])
    assert result['receipt_state'] == 'verified'
    phases = [event[0] for event in events]
    assert phases.index('backup') < phases.index('write') < phases.index('verify')
    writes = [event for event in events if event[0] == 'write']
    assert writes[-1][1] == writes[-1][2] == result['applied']
    backups = [event for event in events if event[0] == 'backup' and len(event) == 3]
    assert backups[-1][1] == backups[-1][2] == result['backup']['files']


def test_job_routes_share_existing_same_origin_protection(editor):
    instance, url = editor
    status, _ = call(url + '/apply-job', 'POST', {'plan_id': 'none'}, headers={'Origin': 'http://evil.example'})
    assert status == 403
    status, body = call(url + '/apply-job', 'POST', {'plan_id': 'none'})
    assert status == 200
    job = json.loads(body)
    state = wait_job(instance, job)
    assert state['error']['error'] == 'plan_not_found'
    status, body = call(url + '/jobs/' + job['job_id'])
    assert status == 200
    assert json.loads(body)['state'] == 'failed'
