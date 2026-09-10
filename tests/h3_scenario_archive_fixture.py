"""Chunked synthetic inventories with the production source record schema."""
from collections import Counter
from copy import deepcopy
import gzip
import json
from pathlib import Path
import re


def write_archive(directory, data, per_chunk=7):
    directory = Path(directory)
    (directory / 'records').mkdir(exist_ok=True)
    groups = []
    for row in data['records']:
        root = re.match(r'.*?#[0-9]+', row['address']).group()
        if not groups or groups[-1][0] != root:
            groups.append((root, []))
        groups[-1][1].append(row)
    chunks = []
    for root, rows in groups:
        for offset in range(0, len(rows), per_chunk):
            part = rows[offset:offset+per_chunk]
            raw = b''.join(json.dumps(r, separators=(',', ':'), allow_nan=False).encode() + b'\n' for r in part)
            packed = gzip.compress(raw, compresslevel=1, mtime=0)
            path = f'records/{len(chunks):06d}.jsonl.gz'
            (directory / path).write_bytes(packed)
            chunks.append(dict(file=path, bytes=len(packed), raw_bytes=len(raw), count=len(part),
                               root_address=root, root_name=root.rsplit('#', 1)[0]))
    diagnostics = Counter()
    for row in data['records']:
        if row['kind'] == 'resource_header_only':
            diagnostics['resource_payload_not_decoded'] += 1
        if isinstance(row.get('value'), dict) and 'representation' in row['value']:
            diagnostics['value_retained_as_decoder_debug'] += 1
    result = {k: deepcopy(v) for k, v in data.items() if k not in ('records', 'references', 'diagnostics')}
    result.update(version=2, encoding='gzip-jsonl', chunks=chunks, record_count=len(data['records']),
                  raw_bytes=sum(c['raw_bytes'] for c in chunks), compressed_bytes=sum(c['bytes'] for c in chunks),
                  reference_count=sum(r['kind'] == 'value' and isinstance(r.get('value'), dict) and 'group' in r['value'] for r in data['records']),
                  blob_count=sum(r['kind'] == 'data' for r in data['records']),
                  blob_bytes=sum(r['bytes'] for r in data['records'] if r['kind'] == 'data'),
                  diagnostics=[dict(code=k, count=v) for k, v in diagnostics.items()])
    (directory / 'scenario.h3inspect.json').write_text(json.dumps(result), encoding='utf-8')
    return result
