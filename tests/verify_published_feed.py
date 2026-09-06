"""Require published metadata, index and archive to match the tested package."""
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen

directory = Path('site/api/v1/extensions')
expected = json.loads((directory / 'build.json').read_text())
archive = (directory / 'io_scene_foundry.zip').read_bytes()
digest = 'sha256:' + hashlib.sha256(archive).hexdigest()
base = os.environ['PAGE_URL'].rstrip('/') + '/api/v1/extensions/'

def fetch(name):
    request = Request(base + name, headers={'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=30) as response:
        data = response.read(128 * 1024 * 1024 + 1)
    if len(data) > 128 * 1024 * 1024:
        raise ValueError('Published response exceeds 128 MiB')
    return data

for attempt in range(12):
    try:
        actual = json.loads(fetch('build.json'))
        if actual != expected:
            raise ValueError(f'Build metadata mismatch: {actual}')
        entries = [e for e in json.loads(fetch('index.json'))['data'] if e['id'] == 'io_scene_foundry']
        if len(entries) != 1:
            raise ValueError('Expected one Foundry extension entry')
        entry = entries[0]
        if (entry['version'] != expected['version'] or entry['archive_hash'] != digest
                or entry['archive_size'] != len(archive) or entry['archive_url'] != './io_scene_foundry.zip'):
            raise ValueError('Published index does not match the tested extension')
        downloaded = fetch('io_scene_foundry.zip')
        if len(downloaded) != len(archive) or 'sha256:' + hashlib.sha256(downloaded).hexdigest() != digest:
            raise ValueError('Published archive does not match the tested extension')
        print('FEED_VERIFIED ' + json.dumps({**expected, 'index_url': base + 'index.json',
                                           'archive_hash': digest, 'archive_size': len(archive)}))
        break
    except (OSError, ValueError, KeyError, TypeError) as error:
        if attempt == 11:
            raise
        print(f'Waiting for Pages propagation ({attempt + 1}/12): {error}', flush=True)
        time.sleep(10)
