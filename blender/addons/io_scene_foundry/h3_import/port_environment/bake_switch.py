"""Switch captured lighting comparison states with exact ownership/hash checks.

No bake or import is performed. A comparison receipt must capture both states
outside the kits. Unrecognized user edits reject the entire preflight.
"""
from pathlib import Path
import shutil
from .paths import OutputPaths, Ownership, digest


def switch(receipt, variant, *, dry_run=False):
    paths = OutputPaths(receipt['h3_root'], receipt['reach_root'], receipt['namespace'], allow_nested=True)
    states = receipt['variants']
    if variant not in states or len(states) != 2:
        raise ValueError('Expected one of two captured comparison states')
    current = paths.snapshot()
    matches = [name for name, state in states.items() if state['files'] == current]
    if not matches:
        raise ValueError('Current outputs contain unrecognized edits; nothing was changed')
    before = states[matches[0]]['files']; after = states[variant]['files']
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    copies = []
    for key in changed:
        if not key.startswith('tags/'+paths.namespace+'/'):
            raise ValueError('Comparison cannot change data or another namespace')
        target = paths.owned_tag(key[len('tags/'):])
        allowed = {'.scenario', '.scenario_lightmap', '.scenario_lightmap_bsp_data', '.scenario_faux_data', '.probestore'}
        if target.suffix == '.bitmap' and ('/faux/' in key or 'lightmap' in key):
            allowed.add('.bitmap')
        if key == receipt['diagnostic_lighting_key']:
            allowed.add('.scenario_structure_lighting_info')
        if target.suffix not in allowed:
            raise ValueError('Comparison cannot change BSP geometry, collision, shaders or sky')
        root = Path(states[variant]['capture_root']).resolve(strict=True)
        Ownership(paths, root)  # Captures must be outside both kits.
        source = (root/key).resolve()
        if not source.is_relative_to(root):
            raise ValueError('Comparison source escapes its capture directory')
        if key in after and (not source.is_file() or digest(source) != after[key]):
            raise ValueError('Captured comparison file is absent or changed: '+key)
        copies.append((key, source, target))
    result = dict(from_variant=matches[0], to_variant=variant, changed_files=changed, dry_run=dry_run)
    if dry_run or not changed:
        return result
    # The complete two-state capture remains available if an OS write fails.
    # Recheck immediately before the first write; never merge around user edits.
    if paths.snapshot() != current:
        raise ValueError('Outputs changed during comparison preflight')
    for key, source, target in copies:
        if key in after:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            target.unlink()  # One verified owned file, never recursive deletion.
    if paths.snapshot() != after:
        raise ValueError('Comparison readback failed; captured states remain available')
    return result
