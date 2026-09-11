"""Conservative reuse of completed native object batches."""

from .model import stable_hash
from .paths import digest
from pathlib import Path


def rule_fingerprint(row):
    """Hash only modules participating in this root's native object authoring.

    Scenario population and unrelated family adapters do not invalidate object
    assets. Materials retain their own closure/recipe identities separately.
    """
    directory=Path(__file__).resolve().parent
    names={'object_worker.py','native_object_tags.py','object_ir.py'}
    if row.get('object_ir',{}).get('physics_model'):
        names.update({'physics_association.py','native_physics.py'})
    files={str(directory/name):digest(directory/name) for name in sorted(names)}
    return stable_hash(files)


def root_identity(source_tag, source_group, source_hashes, rule_fingerprint,
                  closure_fingerprint, destination):
    """Separate stable asset identity from source and translator revisions."""
    if not source_hashes or not rule_fingerprint or not closure_fingerprint:
        raise ValueError('Root reuse requires complete source, rule and closure identities')
    logical = dict(source_tag=source_tag.replace('\\', '/').lower(), source_group=source_group,
                   target_tag=destination.replace('\\', '/').lower())
    return dict(**logical, logical_sha256=stable_hash(logical),
                source_revision_sha256=stable_hash(source_hashes),
                source_hashes=dict(source_hashes), rule_fingerprint=rule_fingerprint,
                closure_fingerprint=closure_fingerprint)


def reusable_root(receipt, identity, current_files):
    """Per-root reuse; neither a batch plan nor unrelated output can invalidate it.

    Callers mint receipts only after native reopen validation of the complete
    root closure. A mere file-presence inventory is never a native receipt.
    """
    if receipt.get('status') != 'NATIVE_AUTHORED_READBACK_VERIFIED':
        return False
    if receipt.get('identity') != identity or not receipt.get('native_readback'):
        return False
    outputs = receipt.get('output_files', {})
    return bool(outputs) and all(current_files.get(p) == sha for p, sha in outputs.items())


def verify_reuse(receipt,plan,current_files,retry_sources=None):
    if receipt['status']!='COMPLETE' or receipt['plan_sha256']!=plan['plan_sha256']:
        raise ValueError('Prior native receipt is incomplete or from another plan')
    files={r['path']:r['sha256'] for r in receipt['generated_files']}
    if not files or any(current_files.get(p)!=h for p,h in files.items()):
        raise ValueError('Prior native receipt outputs changed or are missing')
    rows=receipt['worker']['objects'];known={r['source_tag'] for r in rows}
    expected={r['source_tag']:r['target_tag'] for r in plan['objects'] if r['plan_status']=='READY_FOR_NATIVE'}
    if known!=expected.keys() or len(known)!=len(rows):raise ValueError('Retry requires complete source accounting')
    if any(r['status'] not in {'NATIVE_COMPILED','DEFERRED'} or r['target_tag']!=expected[r['source_tag']] for r in rows):
        raise ValueError('Prior object results are incomplete or have different native identities')
    if retry_sources and set(retry_sources)-known:raise ValueError('Retry identities absent from prior batch')
    return len(files)
