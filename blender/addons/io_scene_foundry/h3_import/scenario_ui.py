"""Thin source adapter for the existing Foundry import operators and dialog."""
import json
import os
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import subprocess

import bpy
from .. import utils
from .scenario_options import INSPECTION_PROPERTIES, ScenarioOptions, classify_source
from .scenario_content import tag_reference


# RNA search/enum callbacks receive OperatorProperties, not the Python Operator.
# Keep callback state outside both wrappers. Cached values contain no Blender IDs.
_last_selection_keys = OrderedDict()
_enum_strings = {}
_NONE_SKY_ITEMS = (('none', 'None', ''),)


@dataclass(frozen=True)
class SelectionState:
    source: str | None = None
    error: str = ''
    skies: tuple = ()
    enum_items: tuple = _NONE_SKY_ITEMS
    search_items: tuple = ()


def _stamp(path):
    try:
        stat = Path(path).stat()
        return stat.st_size, stat.st_mtime_ns
    except OSError:
        return None


def _selection_key(operator, path=None):
    path = path if path is not None else getattr(operator, 'filepath', '')
    if not path or Path(path).suffix.lower() != '.scenario': return None
    path = bpy.path.abspath(path)
    prefs = utils.get_prefs()
    helper = prefs.h3_extraction_helper
    return (path, utils.get_tags_path(), prefs.h3_tags_root, helper, _stamp(path),
            _stamp(bpy.path.abspath(helper)) if helper else None)


@lru_cache(maxsize=32)
def _selection_state(key):
    if key is None: return SelectionState()
    source = None
    try:
        source, _ = classify(key[0])
        rows = tuple(selection(key[0])) if source == 'halo3' else ()
        # Blender retains pointers to dynamic enum strings beyond the callback.
        # Keep these small strings alive even when a source-cache entry is evicted.
        def retain(value): return _enum_strings.setdefault(value, value)
        items = _NONE_SKY_ITEMS + tuple(tuple(retain(v) for v in (
            f"h3:{r['index']}", f"{r['index']}: {Path(r['source_tag']).stem}", r['source_tag']))
            for r in rows if r['source_tag'])
        search = tuple((f"{r['index']}: {r['source_tag']}", r['source_tag']) for r in rows if r['source_tag'])
        return SelectionState(source=source, skies=rows, enum_items=items, search_items=search)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return SelectionState(source=source, error=str(error))


def selection_state(operator, path=None):
    return _selection_state(_selection_key(operator, path))


def scenario_properties(cls):
    for name, label in INSPECTION_PROPERTIES.items():
        cls.__annotations__[name] = bpy.props.BoolProperty(name=label, default=False,
            description='Optional H3 inspection data; imported hidden and excluded from export')
    return cls


def classify(path):
    configured = utils.get_prefs().h3_tags_root.strip()
    return classify_source(bpy.path.abspath(path), utils.get_tags_path(),
                           bpy.path.abspath(configured) if configured else None)


def sky_rows(selection):
    rows = []
    for row in selection['skies']:
        refs = [f['value'] for f in row['fields'] if f['name'] == 'sky']
        source = tag_reference(refs[0]) if len(refs) == 1 and refs[0] and refs[0].get('path') else ''
        rows.append(dict(index=row['index'], source_tag=source, fields=row['fields']))
    return rows


def selection(path):
    from . import _source_paths
    root, helper = _source_paths(Path(path).resolve(strict=True))
    helper = helper.with_name('h3-scenario-inspect.exe' if os.name == 'nt' else 'h3-scenario-inspect')
    result = subprocess.run([str(helper), '--tags-root', str(root), '--input', str(Path(path).resolve()),
                             '--selection-json'], capture_output=True, text=True, timeout=60,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('H3 scenario selection failed: ' + result.stderr[-1500:])
    return sky_rows(json.loads(result.stdout))


def refresh(operator):
    key = _selection_key(operator)
    _selection_state(key)
    pointer = operator.as_pointer()
    changed = pointer not in _last_selection_keys or _last_selection_keys[pointer] != key
    _last_selection_keys[pointer] = key
    _last_selection_keys.move_to_end(pointer)
    if len(_last_selection_keys) > 32: _last_selection_keys.popitem(last=False)
    return changed


def draw_inspection(operator, layout):
    state = selection_state(operator)
    if state.error:
        layout.label(text=state.error, icon='ERROR')
    if state.source != 'halo3': return
    box = layout.box()
    box.label(text='Advanced Scenario Inspection')
    for name in INSPECTION_PROPERTIES:
        if name == 'h3_detailed_points' and not operator.h3_inspect_firing_positions: continue
        box.prop(operator, name)
    box.label(text='Optional collections start hidden in the viewport')


def sky_items(operator, context):
    return selection_state(operator).enum_items


def search_skies(operator, context, edit_text):
    return selection_state(operator).search_items


def route(operator, context, paths):
    """Return None for the untouched Reach backend. Never let H3 reach MB."""
    sources = [classify(path)[0] for path in paths if Path(path).suffix.lower() == '.scenario']
    if 'halo3' not in sources: return None
    if len(paths) != 1:
        raise ValueError('Import one H3 scenario at a time; mixed-source selections are not supported')
    if getattr(operator, 'tag_zone_set', '') not in ('', 'all_zone_sets'):
        raise ValueError('H3 Zone Set filtering is not available in this checkpoint; choose All Zone Sets')
    from . import ScenarioImportJob
    from .scenario_assets import selected_sky
    options = ScenarioOptions.from_operator(operator)
    if options.sky and options.sky.lower().strip() != 'none':
        state = selection_state(operator, paths[0])
        if state.error: raise ValueError(state.error)
        selected_sky(state.skies, options.sky)
    operator._h3_job = ScenarioImportJob(operator, options)
    operator._h3_job.filepath = paths[0]
    return operator._h3_job.execute(context)
