"""Read bounded scenario record chunks and retain them without full expansion."""
import base64
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import tempfile

CHUNK_BYTES = 8 * 1024 * 1024
TOTAL_BYTES = 8 * 1024 * 1024 * 1024
COMPRESSED_BYTES = 512 * 1024 * 1024
CHUNK_PATH = re.compile(r'records/[0-9]{6,}\.jsonl\.gz\Z')


def validate(data, directory=None):
    from . import scenario_inspection as legacy
    # Reuse the source identity and scope contract without manufacturing records.
    header = dict(data, version=1, records=[], references=[], diagnostics=[])
    legacy.validate(header)
    if type(data.get('version')) is not int or data['version'] != 2 or data.get('encoding') != 'gzip-jsonl':
        raise legacy.InspectionError('Unsupported scenario record encoding')
    chunks = data.get('chunks')
    if not isinstance(chunks, list) or len(chunks) > 65_536:
        raise legacy.InspectionError('Invalid inventory chunk table')
    seen, roots = set(), {}
    totals = Counter()
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise legacy.InspectionError('Invalid inventory chunk')
        relative = chunk.get('file')
        if not isinstance(relative, str) or not CHUNK_PATH.fullmatch(relative) or relative in seen:
            raise legacy.InspectionError('Invalid or duplicate inventory chunk path')
        seen.add(relative)
        for name in ('root_address', 'root_name'):
            if not isinstance(chunk.get(name), str):
                raise legacy.InspectionError('Missing inventory section identity')
        address = chunk['root_address']
        prefix = chunk['root_name'] + '#'
        if (not address.startswith(prefix) or not address[len(prefix):].isdigit()
                or roots.setdefault(address, chunk['root_name']) != chunk['root_name']):
            raise legacy.InspectionError('Conflicting inventory section identities')
        for name in ('count', 'bytes', 'raw_bytes'):
            totals[name] += legacy._int(chunk.get(name), name, 1)
        if chunk['raw_bytes'] > CHUNK_BYTES or chunk['bytes'] > CHUNK_BYTES + 65536:
            raise legacy.InspectionError('Inventory chunk exceeds byte limit')
    if totals['raw_bytes'] > TOTAL_BYTES or totals['bytes'] > COMPRESSED_BYTES:
        raise legacy.InspectionError('Scenario inventory exceeds byte budget')
    for name, actual in [('record_count', totals['count']), ('raw_bytes', totals['raw_bytes']),
                         ('compressed_bytes', totals['bytes'])]:
        if legacy._int(data.get(name), name) != actual:
            raise legacy.InspectionError('Inventory summary mismatch: ' + name)
    for name in ('reference_count', 'blob_count', 'blob_bytes'):
        legacy._int(data.get(name), name)
    if data['blob_bytes'] > legacy.MAX_BLOB_BYTES:
        raise legacy.InspectionError('Scenario blobs exceed size limit')
    diagnostics = data.get('diagnostics')
    if not isinstance(diagnostics, list):
        raise legacy.InspectionError('Missing inventory diagnostics')
    codes = set()
    for row in diagnostics:
        if not isinstance(row, dict) or not isinstance(row.get('code'), str) or row['code'] in codes:
            raise legacy.InspectionError('Invalid inventory diagnostic summary')
        codes.add(row['code'])
        legacy._int(row.get('count'), 'diagnostic count', 1)
    return data


def decode_chunk(content, chunk):
    from . import scenario_inspection as legacy
    if len(content) != chunk['bytes']:
        raise legacy.InspectionError('Truncated inventory chunk: ' + chunk['file'])
    count = size = 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content), mode='rb') as handle:
            while True:
                line = handle.readline(CHUNK_BYTES + 1)
                if not line:
                    break
                size += len(line)
                count += 1
                if size > chunk['raw_bytes'] or count > chunk['count'] or not line.endswith(b'\n'):
                    raise legacy.InspectionError('Inventory chunk length mismatch: ' + chunk['file'])
                row = json.loads(line, object_pairs_hook=legacy._pairs, parse_constant=_bad_constant)
                if not isinstance(row, dict) or not isinstance(row.get('address'), str):
                    raise legacy.InspectionError('Invalid scenario field record')
                address, root = row['address'], chunk['root_address']
                if not (address == root or address.startswith(root + '/') or address.startswith(root + '[')):
                    raise legacy.InspectionError('Record is outside its inventory section')
                yield row
    except (OSError, EOFError) as error:
        raise legacy.InspectionError('Damaged inventory chunk: ' + chunk['file']) from error
    if size != chunk['raw_bytes'] or count != chunk['count']:
        raise legacy.InspectionError('Inventory chunk count mismatch: ' + chunk['file'])


def _bad_constant(value):
    from .scenario_inspection import InspectionError
    raise InspectionError('Nonfinite inventory value: ' + value)


class Archive(dict):
    """The mapping is serializable; file providers and validation state are not."""
    def __init__(self, data, provider):
        super().__init__(data)
        self.provider = provider
        self.hashes = {}
        self.blobs = []

    def chunk_bytes(self, chunk):
        from .scenario_inspection import InspectionError
        data = self.provider(chunk)
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != chunk['bytes'] or digest != self.hashes.setdefault(chunk['file'], digest):
            raise InspectionError('Inventory chunk changed during import: ' + chunk['file'])
        return data

    def records(self, roots=None):
        for chunk in self['chunks']:
            if roots is None or chunk['root_name'] in roots:
                yield from decode_chunk(self.chunk_bytes(chunk), chunk)

    def validate_records(self, directory=None, progress=None):
        from . import scenario_inspection as legacy
        processed = 0
        totals = Counter()
        diagnostics = Counter()
        self.blobs = []
        # Keep exact duplicate detection off the Blender heap for million-field tables.
        with tempfile.TemporaryDirectory(prefix='foundry_h3_inventory_') as temporary:
            with closing(sqlite3.connect(str(Path(temporary) / 'addresses.sqlite'))) as db:
                db.execute('PRAGMA journal_mode=OFF')
                db.execute('PRAGMA synchronous=OFF')
                db.execute('PRAGMA cache_size=-4096')
                db.execute('CREATE TABLE fields (address TEXT PRIMARY KEY) WITHOUT ROWID')
                db.execute('CREATE TABLE blobs (path TEXT PRIMARY KEY) WITHOUT ROWID')
                for chunk in self['chunks']:
                    rows = list(decode_chunk(self.chunk_bytes(chunk), chunk))
                    references = [{'address': row['address'], 'reference': row['value']} for row in rows
                                  if row.get('kind') == 'value' and isinstance(row.get('value'), dict)
                                  and 'group' in row['value']]
                    legacy.validate(dict(self, version=1, records=rows, references=references, diagnostics=[]), directory)
                    try:
                        db.executemany('INSERT INTO fields VALUES (?)', ((row['address'],) for row in rows))
                        for row in rows:
                            kind = row['kind']
                            if kind == 'data':
                                db.execute('INSERT INTO blobs VALUES (?)', (row['file'],))
                                self.blobs.append(row)
                                totals['blob_bytes'] += row['bytes']
                            if kind == 'resource_header_only':
                                diagnostics['resource_payload_not_decoded'] += 1
                            if isinstance(row.get('value'), dict) and 'representation' in row['value']:
                                diagnostics['value_retained_as_decoder_debug'] += 1
                    except sqlite3.IntegrityError as error:
                        raise legacy.InspectionError('Duplicate field address or blob across inventory chunks') from error
                    totals['reference_count'] += len(references)
                    db.commit()
                    processed += len(rows)
                    if progress:
                        progress(f'Validating inventory: {processed}/{self["record_count"]} fields')
        totals['blob_count'] = len(self.blobs)
        for name in ('reference_count', 'blob_count', 'blob_bytes'):
            if totals[name] != self[name]:
                raise legacy.InspectionError('Inventory summary mismatch: ' + name)
        if dict(diagnostics) != {row['code']: row['count'] for row in self['diagnostics']}:
            raise legacy.InspectionError('Inventory diagnostic counts mismatch')
        return self


def load(data, directory, progress=None):
    from . import scenario_inspection as legacy
    validate(data)
    root = Path(directory).resolve(strict=True)
    def provider(chunk):
        path = (root / legacy.relative_path(chunk['file'])).resolve(strict=True)
        if not path.is_relative_to(root):
            raise legacy.InspectionError('Inventory chunk escapes extraction directory')
        with path.open('rb') as handle:
            return handle.read(chunk['bytes'] + 1)
    return Archive(data, provider).validate_records(root, progress=progress)


def from_packed(data, entries, text):
    """Query retained records after the extraction directory has been removed."""
    from . import scenario_inspection as legacy
    validate(data)
    if not isinstance(entries, list) or len(entries) != len(data['chunks']):
        raise legacy.InspectionError('Packed inventory index mismatch')
    by_file = {}
    for entry, chunk in zip(entries, data['chunks']):
        if (entry.get('file') != chunk['file'] or entry.get('encoding') != 'gzip+base64'
                or not isinstance(entry.get('text'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', entry.get('sha256', ''))):
            raise legacy.InspectionError('Invalid packed inventory entry')
        by_file[entry['file']] = entry
    def provider(chunk):
        entry = by_file[chunk['file']]
        encoded = text(entry['text'])
        limit = ((chunk['bytes'] + 2) // 3) * 4
        # New retained text wraps at 76 columns; keep reading old single lines.
        if len(encoded) > limit + (limit + 75) // 76:
            raise legacy.InspectionError('Packed inventory exceeds byte limit')
        encoded = encoded.replace('\n', '')
        if len(encoded) > limit:
            raise legacy.InspectionError('Packed inventory exceeds byte limit')
        content = base64.b64decode(encoded, validate=True)
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise legacy.InspectionError('Packed inventory checksum mismatch')
        return content
    return Archive(data, provider).validate_records()
