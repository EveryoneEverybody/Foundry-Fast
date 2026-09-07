"""Opt-in real import through the registered Foundry operator, outside the source tree.

blender --background --factory-startup --python-exit-code 1 --python this.py --
    --source /H3EK/tags/...scenario --helper /helpers/h3-object-bridge.exe --output /reports
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import time
from types import SimpleNamespace

import bpy

args = argparse.ArgumentParser()
args.add_argument('--source', required=True)
args.add_argument('--helper', required=True)
args.add_argument('--output', required=True)
args.add_argument('--inspection', action='store_true')
args.add_argument('--no-objects', action='store_true')
args.add_argument('--no-sky', action='store_true')
args.add_argument('--no-materials', action='store_true')
args.add_argument('--no-geometry', action='store_true')
opts = args.parse_args(sys.argv[sys.argv.index('--') + 1:])
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'blender/addons'))
bpy.ops.preferences.addon_enable(module='io_scene_foundry')
from io_scene_foundry import utils, h3_import
from io_scene_foundry.h3_import.scenario_reporting import memory_metrics

source = Path(opts.source).resolve(strict=True)
tags = next(p for p in source.parents if p.name.lower() == 'tags')
output = Path(opts.output).resolve()
assert not output.is_relative_to(tags)
output.mkdir(parents=True, exist_ok=True)
prefs = utils.get_prefs()
prefs.h3_tags_root = str(tags)
prefs.h3_extraction_helper = str(Path(opts.helper).resolve(strict=True))
settings = utils.get_scene_props()
settings.scene_project = utils.get_project().name
settings.asset_type = 'scenario'
settings.scale = 'blender'; settings.forward_direction = 'x'
project_before = (settings.scene_project, utils.get_tags_path())
source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
memory_before = memory_metrics()
source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
started = time.perf_counter()
result = bpy.ops.nwo.foundry_import(filepath=str(source), tag_bsp_import_geometry=not opts.no_geometry,
    tag_sky='' if opts.no_sky else 'h3:0', tag_scenario_import_objects=not opts.no_objects,
    build_blender_materials=not opts.no_materials, tag_bsp_render_only=True, setup_as_asset=False,
    h3_inspect_ai=opts.inspection, h3_inspect_giant_hints=opts.inspection,
    h3_inspect_firing_positions=opts.inspection)
assert result == {'RUNNING_MODAL'}, result
job = h3_import._active[-1]
while result == {'RUNNING_MODAL'}:
    result = job.modal(bpy.context, SimpleNamespace(type='TIMER'))
    if result == {'RUNNING_MODAL'}: time.sleep(.1)
elapsed = time.perf_counter() - started
assert result == {'FINISHED'}, result
assert project_before == (settings.scene_project, utils.get_tags_path())
assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
session = job._session
if not opts.no_materials:
    material_report = json.loads(bpy.data.texts[session.root['h3_material_report']].as_string())
    assert session.profile.counts['unique_images'] > 0, 'Material extraction produced no packed images'
    assert any(r.get('preview', {}).get('status') == 'approximate_preview' for r in material_report if r.get('preview'))
    sky_shaders = [m for m in bpy.data.materials if '/040_voi/sky/' in m.get('h3_source_shader', '')]
    if not opts.no_sky:
        assert sky_shaders and any(m.get('h3_material_preview') == 'approximate_preview' for m in sky_shaders)
    assert all(not m.nwo.shader_path for m in bpy.data.materials if m.get('h3_source_shader'))
report = dict(seconds=elapsed, baseline_seconds=1469.4,
    improvement_percent=(1469.4-elapsed)/1469.4*100, counts=session.counts,
    profile=session.profile.report(), memory_before=memory_before, memory_after=memory_metrics(),
    project=project_before, source_sha256=source_hash,
    sky=session.sky_entry, warnings=session.warnings,
    helper_output=str(session.directory), source_read_only=True,
    source_commit=source_commit, invocation=vars(opts),
    helper_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(opts.helper).parent.glob('*.exe')},
    comparison='Fresh extraction and construction with a 100 ms modal cadence; OS file cache is uncontrolled; baseline supplied by user')
(output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(output/'040_voi.blend'))
print('REAL_UNIFIED_RESULT', json.dumps({k:report[k] for k in ('seconds','improvement_percent','counts','memory_after','sky')}), flush=True)
