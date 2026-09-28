"""Bounded in-memory jobs; progress only advances when real work reports it."""

import copy
import hashlib
import json
import threading
import time
from contextvars import ContextVar
from uuid import uuid4

from . import operations
from .profile_store import HistoryError

_jobs = {}
_lock = threading.RLock()
_current = ContextVar('profile_job', default=None)
_TTL = 3600
_LIMIT = 100


def report(phase, completed=0, total=None):
    job_id = _current.get()
    if job_id is None:
        return
    with _lock:
        _jobs[job_id].update(phase=phase, completed=completed, total=total)


def _public(job):
    return copy.deepcopy({k: v for k, v in job.items() if k not in {'instance', 'key', 'finished'}})


def get(instance_id, job_id):
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job['instance'] != instance_id:
            raise operations.OperationError('operation_not_found', 404)
        return _public(job)


def start(instance_id, kind, body, work):
    key = hashlib.sha256(json.dumps([kind, body], sort_keys=True).encode()).hexdigest()
    with _lock:
        now = time.monotonic()
        for job_id, job in list(_jobs.items()):
            if job.get('finished') is not None and now - job['finished'] > _TTL:
                del _jobs[job_id]
        for job in _jobs.values():
            if job['instance'] == instance_id and job['key'] == key:
                return _public(job)
        if any(j['instance'] == instance_id and j['state'] in {'queued', 'running'} for j in _jobs.values()):
            raise operations.OperationError('operation_running')
        while len(_jobs) >= _LIMIT:
            finished = [j for j in _jobs.values() if j.get('finished') is not None]
            if not finished:
                raise operations.OperationError('operation_running')
            del _jobs[min(finished, key=lambda j: j['finished'])['job_id']]
        job_id = uuid4().hex
        job = {'job_id': job_id, 'instance': instance_id, 'key': key,
               'state': 'queued', 'phase': 'check', 'completed': 0, 'total': None}
        _jobs[job_id] = job

        def run():
            token = _current.set(job_id)
            with _lock:
                job['state'] = 'running'
            try:
                result = work()
            except (operations.OperationError, HistoryError) as exc:
                with _lock:
                    job.update(state='failed', error={'error': exc.code, **getattr(exc, 'params', {})})
            except Exception:
                with _lock:
                    job.update(state='failed', error={'error': 'operation_failed'})
            else:
                with _lock:
                    job.update(state='succeeded', phase='done', result=result)
            finally:
                with _lock:
                    job['finished'] = time.monotonic()
                _current.reset(token)

        # Non-daemon: an orderly shutdown must not abandon a running write.
        threading.Thread(target=run, name='profile-operation', daemon=False).start()
        return _public(job)
