"""Bounded external workers, polled by the host thread without queues or threads."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from .protocol import VERSION, atomic_json, digest, reservation


class WorkerFailure(RuntimeError):
    pass


class Pool:
    def __init__(self, python, workers=2, budget=512 * 1024 * 1024, timeout=300):
        self.python = str(python)
        self.worker_count = max(1, min(4, int(workers)))
        self.budget = budget
        self.timeout = timeout
        self.folder = Path(tempfile.mkdtemp(prefix='foundry-bitmap-workers-'))
        self.jobs = {}
        self.slots = []
        self.bytes_reserved = 0
        self.stats = defaultdict(float)
        self.closed = False

    def room(self, size=0):
        self.poll()
        return not self.closed and len(self.jobs) < self.worker_count * 2 and self.bytes_reserved + size <= self.budget

    def submit(self, key, recipe, payload):
        if key in self.jobs:
            self.stats['deduplicated'] += 1
            return self.jobs[key]
        recipe = dict(recipe)
        size = reservation(recipe, len(payload))
        if not self.room(size):
            return None
        token = uuid.uuid4().hex
        folder = self.folder / token
        folder.mkdir()
        started = time.perf_counter()
        try:
            (folder / 'pixels.bin').write_bytes(payload)
            request = {'version': VERSION, 'id': token, 'recipe': recipe,
                       'payload_size': len(payload), 'payload_sha256': hashlib.sha256(payload).hexdigest(),
                       'budget': size}
            job = {'key': key, 'folder': folder, 'request': request, 'size': size, 'state': 'queued',
                   'discard': False, 'started': None, 'result': None}
            self.jobs[key] = job
            self.bytes_reserved += size
            self.stats['peak_reserved_bytes'] = max(self.stats['peak_reserved_bytes'], self.bytes_reserved)
            self.stats['submitted'] += 1
            self.stats['input_bytes'] += len(payload)
            self.stats['spool_seconds'] += time.perf_counter() - started
            self.poll()
            return job
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            self.jobs.pop(key, None)
            self.bytes_reserved = sum(j['size'] for j in self.jobs.values())
            raise

    def _spawn(self):
        slot_dir = self.folder / f'worker-{len(self.slots)}'
        slot_dir.mkdir(exist_ok=True)
        log = open(slot_dir / 'worker.log', 'ab')
        env = dict(os.environ)
        for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            env[name] = '1'
        begin = time.perf_counter()
        try:
            process = subprocess.Popen([self.python, '-I', str(Path(__file__).with_name('worker.py')),
                                        '--folder', str(slot_dir), '--parent', str(os.getpid())],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        finally:
            log.close()
        slot = {'folder': slot_dir, 'process': process, 'job': None, 'started': begin, 'ready': None}
        self.slots.append(slot)
        self.stats['processes_started'] += 1
        return slot

    def poll(self):
        if self.closed:
            return
        for slot in self.slots:
            process = slot['process']
            ready_file = slot['folder'] / 'ready.json'
            if slot['ready'] is None and ready_file.exists():
                slot['ready'] = json.loads(ready_file.read_text())
                self.stats['ready_observed_seconds_sum'] += time.perf_counter() - slot['started']
            job = slot['job']
            if job is None:
                continue
            result_file = job['folder'] / 'result.json'
            if result_file.exists():
                result = json.loads(result_file.read_text())
                ready = slot['ready'] or {}
                valid = result.get('version') == VERSION and result.get('id') == job['request']['id'] and result.get('codec') == ready.get('codec')
                if not valid:
                    result = {'ok': False, 'error': 'Worker result identity mismatch'}
                job['result'] = result
                job['state'] = 'ready' if result.get('ok') else 'failed'
                for name in ('decode_seconds', 'color_seconds', 'cubemap_seconds', 'write_seconds', 'elapsed_seconds'):
                    self.stats['worker_' + name] += result.get(name, 0)
                slot['job'] = None
                if job['discard']:
                    self.release(job['key'])
            elif process.poll() is not None or time.perf_counter() - job['started'] > self.timeout:
                if process.poll() is None:
                    process.kill()
                process.wait()
                job.update(state='failed', result={'ok': False, 'error': 'Worker exited or timed out'})
                slot['job'] = None
                if job['discard']:
                    self.release(job['key'])
        for job in tuple(self.jobs.values()):
            if job['state'] != 'queued':
                continue
            slot = next((s for s in self.slots if s['job'] is None and s['process'].poll() is None), None)
            if slot is None and len(self.slots) < self.worker_count:
                slot = self._spawn()
            if slot is None:
                if self.slots and all(s['process'].poll() is not None for s in self.slots):
                    job.update(state='failed', result={'ok': False, 'error': 'No live bitmap workers'})
                break
            atomic_json(slot['folder'] / 'request.json', job['request'])
            slot['job'] = job
            job.update(state='running', started=time.perf_counter())
        running = sum(s['job'] is not None for s in self.slots)
        self.stats['peak_running_jobs'] = max(self.stats['peak_running_jobs'], running)

    def take(self, key, check_cancel=lambda: None):
        job = self.jobs[key]
        started = time.perf_counter()
        while job['state'] in {'queued', 'running'}:
            check_cancel()
            self.poll()
            if job['state'] in {'queued', 'running'}:
                time.sleep(0.01)
        self.stats['host_wait_seconds'] += time.perf_counter() - started
        if job['state'] != 'ready':
            raise WorkerFailure(job['result'].get('error', 'Bitmap preprocessing failed'))
        wanted = {'raw.tiff', 'equirectangular.tiff'} if job['request']['recipe']['cubemap'] else {'raw.tiff'}
        result = job['result']
        if set(result.get('files', {})) != wanted:
            raise WorkerFailure('Worker output set mismatch')
        outputs = {}
        for name in wanted:
            path = job['folder'] / name
            metadata = result['files'][name]
            if path.stat().st_size != metadata['bytes'] or digest(path) != metadata['sha256']:
                raise WorkerFailure('Worker output checksum mismatch')
            outputs[name] = path
        return outputs

    def release(self, key):
        job = self.jobs.get(key)
        if job is None:
            return
        if job['state'] == 'running':
            job['discard'] = True
            return
        self.jobs.pop(key)
        self.bytes_reserved -= job['size']
        shutil.rmtree(job['folder'], ignore_errors=True)

    def close(self):
        if self.closed:
            return
        self.closed = True
        for slot in self.slots:
            process = slot['process']
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        for slot in self.slots:
            slot['process'].wait()
        self.jobs.clear()
        self.bytes_reserved = 0
        shutil.rmtree(self.folder, ignore_errors=True)
