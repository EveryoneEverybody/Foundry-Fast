"""Thin source adapter for the existing Foundry import operators and dialog."""
import json
import os
from pathlib import Path
import subprocess

import bpy
from .. import utils
from .scenario_options import INSPECTION_PROPERTIES, ScenarioOptions, classify_source
from .scenario_content import tag_reference


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
    path = getattr(operator, 'filepath', '')
    if not path or Path(path).suffix.lower() != '.scenario':
        operator._scenario_source = None
        return False
    signature = (path, utils.get_tags_path(), utils.get_prefs().h3_tags_root)
    if getattr(operator, '_scenario_selection_key', None) == signature:
        return False
    operator._scenario_selection_key = signature
    operator._scenario_source = None
    operator._scenario_error = ''
    operator._h3_skies = []
    try:
        operator._scenario_source, _ = classify(path)
        if operator._scenario_source == 'halo3':
            operator._h3_skies = selection(path)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        operator._scenario_error = str(error)
    return True


def draw_inspection(operator, layout):
    if getattr(operator, '_scenario_error', ''):
        layout.label(text=operator._scenario_error, icon='ERROR')
    if getattr(operator, '_scenario_source', None) != 'halo3': return
    box = layout.box()
    box.label(text='Advanced Scenario Inspection')
    for name in INSPECTION_PROPERTIES:
        if name == 'h3_detailed_points' and not operator.h3_inspect_firing_positions: continue
        box.prop(operator, name)
    box.label(text='Optional collections start hidden in the viewport')


def sky_items(operator, context):
    # Retain enum strings on the operator for Blender's dynamic enum lifetime.
    operator._sky_enum_items = [('none', 'None', '')] + [
        (f"h3:{r['index']}", f"{r['index']}: {Path(r['source_tag']).stem}", r['source_tag'])
        for r in getattr(operator, '_h3_skies', []) if r['source_tag']]
    return operator._sky_enum_items


def search_skies(operator, context, edit_text):
    refresh(operator)
    return [(f"{r['index']}: {r['source_tag']}", r['source_tag']) for r in getattr(operator, '_h3_skies', [])
            if r['source_tag']]


def route(operator, context, paths):
    """Return None for the untouched Reach backend. Never let H3 reach MB."""
    sources = [classify(path)[0] for path in paths if Path(path).suffix.lower() == '.scenario']
    if 'halo3' not in sources: return None
    if len(paths) != 1:
        raise ValueError('Import one H3 scenario at a time; mixed-source selections are not supported')
    if getattr(operator, 'tag_zone_set', '') not in ('', 'all_zone_sets'):
        raise ValueError('H3 Zone Set filtering is not available in this checkpoint; choose All Zone Sets')
    from . import ScenarioImportJob
    operator._h3_job = ScenarioImportJob(operator, ScenarioOptions.from_operator(operator))
    operator._h3_job.filepath = paths[0]
    return operator._h3_job.execute(context)
