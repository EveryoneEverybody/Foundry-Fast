"""Capture, compare actual bitmap payloads, and restore an owned diagnostic."""
import json
from pathlib import Path
import shutil
import subprocess

from . import bake_switch
from .paths import atomic_json, digest


def capture_compare_restore(paths, run, before, diagnostic_path, config, blob):
    after = paths.snapshot()
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    for key in changed:
        target = run/'after'/key
        if key in after:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.reach/key, target)
            if digest(target) != after[key]:
                raise ValueError('Diagnostic capture hash mismatch: '+key)
    receipt = dict(h3_root=str(paths.h3), reach_root=str(paths.reach), namespace=paths.namespace,
        diagnostic_lighting_key='tags/'+diagnostic_path, variants={
            'baseline': dict(files=before, capture_root=str(run/'before')),
            'diagnostic': dict(files=after, capture_root=str(run/'after'))})
    atomic_json(run/'comparison-receipt.json', receipt)
    if config.get('sun_diagnostic'):
        # Restore this single hash-pinned diagnostic input even if validation
        # failed. Successful complete-XML readback is recorded by the runner,
        # separately from this receipt's permission to undo an experiment.
        receipt['sun_control_key'] = 'tags/'+diagnostic_path
        receipt['sun_control_kind'] = 'ANALYTIC_SUN_INPUT'
        atomic_json(run/'comparison-receipt.json', receipt)
    # Preflight restore before potentially expensive read-only analysis. This
    # rejects unexpected geometry/user edits; it never expands write authority.
    bake_switch.switch(receipt, 'baseline', dry_run=True)
    result = dict(changed_files=changed, pixel_payloads=[], status='CAPTURED')
    try:
        for name in ('main.blob',):
            source = blob/name
            if source.is_file():
                dest = run/'faux-intermediate'/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
                result['faux_intermediate'] = dict(path=str(dest), sha256=digest(dest), bytes=dest.stat().st_size)
        helper = Path(config['pixel_comparison_helper'])
        if digest(helper) != config['pixel_comparison_helper_sha256']:
            raise ValueError('Pinned bitmap payload comparison helper changed')
        keys = sorted(k for k in before if k.endswith('.bitmap') and 'lightmap' in k)
        if not keys:
            raise ValueError('No baseline lightmap bitmaps')
        for key in keys:
            # Unchanged tag files are also compared. Metadata hashes alone do
            # not establish whether a bake changed encoded pixels.
            diagnostic = run/'after'/key if key in changed else paths.reach/key
            command = [str(helper), str(run/'before'/key), str(diagnostic)]
            p = subprocess.run(command, capture_output=True, text=True, check=False)
            if p.returncode:
                raise RuntimeError('Pixel payload comparison failed: '+p.stderr)
            row = json.loads(p.stdout)
            row.update(key=key, command=command, exit_code=p.returncode)
            result['pixel_payloads'].append(row)
        result['changed_pixel_bytes'] = sum(r['changed_pixel_bytes'] for r in result['pixel_payloads'])
        result['status'] = 'PIXEL_RESPONSE' if result['changed_pixel_bytes'] else 'NO_PIXEL_RESPONSE'
    except Exception as exc:
        result.update(status='COMPARISON_FAILED', error=str(exc))
        raise
    finally:
        result['restoration'] = bake_switch.switch(receipt, 'baseline')
        result['baseline_restored_exactly'] = paths.snapshot() == before
        atomic_json(run/'pixel-payload-comparison.json', result)
    return result
