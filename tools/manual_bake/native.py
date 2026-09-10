"""Background Blender native preflight/prepare/readback. Never invokes Tool."""
import json
import math
import os
from pathlib import Path
import sys
import traceback
from copy import deepcopy
from types import SimpleNamespace


def main(config):
    addon = Path(config['addon']).resolve()
    sys.path[:0] = [str(addon.parent), str(addon / 'h3_import')]
    from port_environment import worker, native_scene
    from port_environment.light_units import attenuation_record
    from port_environment.model import stable_hash
    run = Path(config['native_run']); run.mkdir(exist_ok=False)
    worker.dependencies(addon, run)
    import bpy
    bpy.ops.preferences.addon_enable(module='io_scene_foundry')
    from io_scene_foundry import utils, managed_blam
    from io_scene_foundry.managed_blam import Tag
    utils.module = SimpleNamespace(bl_info={'version': (1, 9, 49)})
    kit = Path(config['kit']).resolve()
    prefs = utils.get_prefs(); prefs.projects.clear(); project = prefs.projects.add()
    project.name = 'Manual lighting preparation'
    project.project_path = str(kit); project.project_xml = str(kit / 'project.xml')
    project.tags_directory = str(kit / 'tags'); project.data_directory = str(kit / 'data'); project.corinth = False
    worker.setup_scene('manual_lighting', 'scenario', config['scenario']+'.sidecar.xml', 'default', project.name)
    os.chdir(kit); managed_blam.mb_init()

    def forbidden(*a, **kw):
        raise RuntimeError('Native lighting preparation/readback cannot start subprocesses or Tool')
    utils.run_tool = forbidden
    import subprocess
    subprocess.Popen = forbidden
    H = managed_blam.Tags

    def load(rel):
        rel = rel.replace('\\', '/')
        path = (kit / 'tags' / rel).resolve()
        if not path.is_relative_to(kit / 'tags') or not path.is_file():
            raise ValueError('Missing or escaping native tag: '+rel)
        t = H.TagFile(); n, e = rel.rsplit('.', 1)
        t.Load(H.TagPath.FromPathAndExtension(n.replace('/', '\\'), e))
        return t

    def value(f):
        if hasattr(f, 'Elements'):
            return [dump(e) for e in f.Elements]
        if hasattr(f, 'Path'):
            return str(f.Path.RelativePathWithExtension).replace('\\', '/') if f.Path else None
        if hasattr(f, 'RawValue'): return int(f.RawValue)
        if hasattr(f, 'Data'):
            d = f.Data
            if isinstance(d, str): return d
            try: return [float(x) for x in d]
            except TypeError:
                try: return float(d)
                except (TypeError, ValueError): return str(d)
        if hasattr(f, 'Value'):
            try: return int(f.Value)
            except (TypeError, ValueError): return str(f.Value)
        try: return str(f.GetStringData())
        except Exception: return None

    def dump(t): return {str(f.DisplayName): value(f) for f in t.Fields}
    def read(rel):
        t = load(rel)
        try:
            if rel.endswith('.scenario_lightmap_bsp_data'):
                return {str(f.DisplayName): value(f) for f in t.Fields if hasattr(f,'Path') or str(f.DisplayName)=='bsp reference index'}
            if rel.endswith('.bitmap'):
                return {'bitmaps': int(t.SelectField('bitmaps').Elements.Count)}
            return dump(t)
        finally: t.Dispose()

    def lightmap_bitmaps(data):
        refs=[v for v in data.values() if isinstance(v,str) and v.endswith('.bitmap')]
        # VMF runtime references omit the retained quadratic source bitmap.
        for rel in list(refs):
            for suffix in ('_dualvmf_pixel_direction_dxtn.bitmap','_dualvmf_pixel_intensity_dxt5.bitmap'):
                if rel.endswith(suffix):
                    source=rel[:-len(suffix)]+'.bitmap'
                    if (kit/'tags'/source).is_file():refs.append(source)
        return sorted(set(refs))

    scenario = read(config['scenario']+'.scenario')
    bsps = [b['structure bsp'] for b in scenario['structure bsps']]
    qualities = read('globals/lightmapper_globals.lightmapper_globals')['quality settings']
    result = dict(status='PASS', bsps=bsps, qualities=qualities, lightmap=scenario.get('new lightmaps'),
                  scenario_bsp_rows=scenario['structure bsps'], runtime_status='RUNTIME_TEST_PENDING')
    selected = config.get('indices', list(range(len(bsps))))
    if config['action'] == 'inspect':
        # Output dependencies may not be isolated by merely cloning a scenario.
        lm = scenario.get('new lightmaps')
        result['output_dependencies'] = []
        if lm:
            result['output_dependencies'].append(lm)
            lightmap = read(lm)
            for row in lightmap['lightmap BSP references']:
                rel = row.get('lightmap bsp data reference')
                if rel:
                    result['output_dependencies'].append(rel)
                    result['output_dependencies'].extend(lightmap_bitmaps(read(rel)))
    if config['action'] in ('prepare', 'validate_inputs'):
        plan = json.loads(Path(config['plan']).read_text(encoding='utf-8-sig'))
        if stable_hash({k:v for k,v in plan.items() if k != 'plan_sha256'}) != plan['plan_sha256']:
            raise ValueError('Accepted plan integrity mismatch')
        if plan.get('unsupported') or plan.get('source_semantic_resolution', {}).get('blocking_records'):
            raise ValueError('Plan has unresolved blocking source contracts')
        if plan['target']['scenario'].replace('\\', '/').removesuffix('.scenario') != config['scenario']:
            raise ValueError('Plan target scenario differs')
        if len(plan['bsps']) != len(bsps) or len(plan['lighting_by_bsp']) != len(bsps):
            raise ValueError('Plan/native BSP count mismatch')
        view = dict(plan, bsps=[], lighting_by_bsp=[]); targets = []; before = {}; records = []
        for i in selected:
            b = plan['bsps'][i]
            if b['destination'].replace('\\', '/') != bsps[i]: raise ValueError('Plan/native BSP identity mismatch')
            lighting = plan['lighting_by_bsp'][i]
            source_tag = bsps[i].rsplit('.',1)[0]+'.scenario_structure_lighting_info'
            dest = source_tag
            if config.get('output_namespace'):
                dest = config['output_namespace']+'/'+Path(source_tag).name
                target = kit/'tags'/dest
                if target.exists(): raise ValueError('Prepare output already exists: '+dest)
                if config['action'] == 'prepare':
                    import shutil
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(kit/'tags'/source_tag, target)
            old = read(source_tag)
            defs = old['generic light definitions']; instances = old['generic light instances']
            if len(defs) != len(lighting['definitions']) or len(instances) != len(lighting['instances']):
                raise ValueError('Accepted plan/native light count mismatch')
            # Refuse a stale or unrelated plan: unchanged authored semantics must agree.
            for d, native in zip(lighting['definitions'], defs):
                for source, field in [('type','type'),('intensity','intensity'),('aspect','aspect'),('color','color')]:
                    if not close(d[source], native[field]): raise ValueError('Plan/native mismatch: '+field)
                shape = {'rectangle':0,'circle':1}[d['source_fields']['shape']]
                if native['shape'] != shape: raise ValueError('Plan/native shape mismatch')
                if d['type'] == 1:
                    for source,field in [('hotspot_size','hotspot size'),('hotspot_cutoff','hotspot cutoff size'),('hotspot_falloff','hotspot falloff speed')]:
                        if not close(d[source],native[field]): raise ValueError('Plan/native cone mismatch')
                if native['flags'] & 3 != int(d['flags']) & 3: raise ValueError('Plan/native attenuation flags mismatch')
            for ip, native in zip(lighting['instances'], instances):
                for key in ('origin','forward','up'):
                    if not close(ip[key], native[key]): raise ValueError('Plan/native instance transform mismatch')
                if ip['definition_index'] != native['definition index']: raise ValueError('Plan/native definition reference mismatch')
            before[dest] = old; targets.append(dest)
            view['bsps'].append(dict(b, destination=dest.rsplit('.',1)[0]+'.scenario_structure_bsp'))
            view['lighting_by_bsp'].append(lighting)
            records.append(dict(bsp=i, path=dest, definitions=[attenuation_record(d) for d in lighting['definitions']]))
        if config['action'] == 'prepare':
            # The real fixed translator + native writer; never the geometry pipeline.
            original_init = Tag.__init__
            def guarded_init(tag, *args, **kw):
                original_init(tag, *args, **kw)
                rel = str(tag.tag_path.RelativePathWithExtension).replace('\\','/')
                if rel not in targets or Path(str(tag.tag_path.Filename)).resolve() != (kit/'tags'/rel).resolve():
                    tag.tag.Dispose(); tag.tag = None
                    raise ValueError('Writer attempted an unselected tag')
            Tag.__init__ = guarded_init
            native_scene.write_static_lights(view, result, attenuation_only=True)
        for row in records:
            actual = read(row['path']) if config['action'] == 'prepare' else before[row['path']]
            probe = config.get('probe')
            if probe and int(probe['Bsp']) == row['bsp']:
                di, ii = int(probe['Definition']), int(probe['Instance'])
                result['solver_probe'] = dict(bsp=row['bsp'], definition=di, instance_index=ii,
                    definition_input=dict(actual['generic light definitions'][di]),
                    instance=dict(actual['generic light instances'][ii]),
                    expected_world=row['definitions'][di]['EXPECTED_FAUX_WORLD_UNITS'])
            for native, expected in zip(actual['generic light definitions'], row['definitions']):
                expected['native_authoring'] = {'near_attenuation': native['near attenuation bounds'], 'far_attenuation': native['far attenuation bounds']}
                expected['matches_corrected_authoring'] = close(expected['native_authoring'], expected['REACH_AUTHORING_UNITS'])
                if config['action'] == 'prepare' and not expected['matches_corrected_authoring']:
                    raise ValueError('Native readback attenuation mismatch')
            old = deepcopy(before[row['path']]); comparison = deepcopy(actual)
            for tag in (old, comparison):
                for d in tag['generic light definitions']:
                    d.pop('near attenuation bounds'); d.pop('far attenuation bounds')
            if old != comparison: raise ValueError('Preparation changed fields outside generic attenuation')
        result['preparation'] = records
        result['needs_preparation'] = any(not d['matches_corrected_authoring'] for r in records for d in r['definitions'])
        result['faux_started'] = False
    if config['action'] == 'verify':
        lm = scenario.get('new lightmaps')
        if not lm: raise ValueError('Scenario has no lightmap')
        refs = read(lm)['lightmap BSP references']; outputs = [lm]
        for i in selected:
            rel = refs[i]['lightmap bsp data reference']; data = read(rel)
            if int(data['bsp reference index']) != i: raise ValueError('Lightmap BSP index mismatch')
            bitmaps = lightmap_bitmaps(data)
            if not bitmaps: raise ValueError('No referenced lightmap bitmaps')
            for bitmap in bitmaps:
                if not read(bitmap).get('bitmaps'): raise ValueError('Empty native bitmap')
            outputs += [rel, *bitmaps]
        result['outputs'] = sorted(set(outputs))
    return result


def close(a, b):
    if isinstance(a, dict): return a.keys() == b.keys() and all(close(v,b[k]) for k,v in a.items())
    if isinstance(a, (tuple,list)): return len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    return math.isclose(float(a),float(b),rel_tol=2e-6,abs_tol=2e-5)


if __name__ == '__main__':
    config = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
    try:
        result = main(config); code = 0
    except BaseException:
        result = dict(status='FAIL', error=traceback.format_exc(), faux_started=False); code = 1
    Path(config['native_result']).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(result['status'],flush=True)
    # Blender cleanup can crash after successful ManagedBlam shutdown. Evidence
    # and explicit status are persisted; avoid unrelated GUI cleanup entirely.
    os._exit(code)
