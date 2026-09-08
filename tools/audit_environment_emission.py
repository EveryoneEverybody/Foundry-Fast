"""Read-only source -> exported GR2 -> native/Faux material identity audit.

Use a captured baseline, never the currently modified diagnostic tag. The
helper reads schema tables only; this script does not invoke Tool or Blender.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(a, b):
    if isinstance(a, (list, tuple)):
        return isinstance(b, (list, tuple)) and len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return abs(float(a) - float(b)) <= 1e-5 * max(1, abs(float(b)))


def native_values(row):
    values = {k: v['value'] for k, v in row.items()}
    # The read-only schema helper retains this composite's named Debug fields.
    color = values['emissive color']
    if isinstance(color, str):
        color = [float(re.search(rf'{c}: ([^,}}]+)', color).group(1)) for c in ('red', 'green', 'blue')]
    values['emissive color'] = color
    return values


def gr2_values(variant):
    f = variant['fields']
    result = {k: f['bungie_lighting_'+k.replace(' ', '_')][0] for k in (
        'emissive power', 'emissive quality', 'emissive focus', 'attenuation falloff', 'attenuation cutoff', 'bounce ratio')}
    result['emissive color'] = [v / 255 for v in f['bungie_lighting_emissive_color'][1:]]
    result['flags'] = int(f['bungie_lighting_emissive_per_unit'][0]) * 2 + int(f['bungie_lighting_use_shader_gel'][0]) * 4
    return result


def audit(args):
    plan = json.loads(args.plan.read_text())
    baseline = json.loads(args.baseline_report.read_text())
    gr2 = json.loads(args.gr2_report.read_text())
    if baseline['lighting_field_readback']['status'] != 'VERIFIED_BEFORE_FAUX':
        raise ValueError('Baseline material readback is not verified')
    captures = []
    def read(key):
        path = args.baseline_capture/key
        if sha(path) != baseline['after'][key]:
            raise ValueError('Baseline captured tag changed: '+key)
        process = subprocess.run([str(args.helper), str(path)], capture_output=True, text=True, check=True)
        value = json.loads(process.stdout)
        captures.append(dict(key=key, sha256=value['sha256']))
        return value['rows']
    namespace = plan['target']['namespace']
    faux = read('tags/'+namespace+'/'+namespace.rsplit('/', 1)[1]+'_faux_data.scenario_faux_data')['global BSP data']
    rows = []
    for bsp_index, (bsp, verified) in enumerate(zip(plan['bsps'], baseline['lighting_field_readback']['bsps'])):
        if verified['bsp'] != bsp['destination']:
            raise ValueError('Baseline BSP ordering changed')
        lighting_path = 'tags/'+bsp['destination'].rsplit('.', 1)[0]+'.scenario_structure_lighting_info'
        native = read(lighting_path)
        materials = read('tags/'+bsp['destination'])['materials']
        native_rows = [native_values(r) for r in native['material info']]
        exported = next(g for g in gr2 if Path(g['path']).name == f"{namespace.rsplit('/',1)[1]}_structure_{bsp['region']}_default.gr2")
        if sha(exported['path']) != exported['sha256']:
            raise ValueError('Exported GR2 changed since inspection')
        by_index = {}
        for binding in verified['emissive']:
            for index in sorted(set(binding['native_material_info_indices'])):
                by_index.setdefault(index, []).append(binding)
        positive = {i for i, row in enumerate(native_rows) if row['emissive power'] > 0}
        if set(by_index) != positive:
            raise ValueError('Positive native rows are not fully covered')
        covered_variants = set()
        for index, bindings in sorted(by_index.items()):
            n = native_rows[index]
            matched = []
            target = bindings[0]['target']
            for binding in bindings:
                if binding['target'] != target or any(not close(n[k], v) for k, v in binding['expected'].items()):
                    raise ValueError('Source/native material mismatch')
            for mesh_index, mesh in enumerate(exported['meshes']):
                for variant_index, variant in enumerate(mesh['variants']):
                    if variant['shader'] != target:
                        continue
                    fields = gr2_values(variant)
                    if all(close(fields[k], v) for k, v in n.items() if k != 'flags') and fields['flags'] == n['flags']['value']:
                        covered_variants.add((mesh_index, variant_index))
                        matched.append(dict(mesh=mesh['mesh'], triangles=variant['triangles'], fields=fields))
            if not matched:
                raise ValueError('Native emissive row lacks matching GR2 triangle annotations')
            native_slots = [i for i, m in enumerate(materials) if m['imported material index']['value'] == index]
            if not native_slots:
                raise ValueError('Emissive row has no BSP material association')
            for slot in native_slots:
                for field in ('render method', 'imported material index'):
                    if materials[slot][field] != faux[bsp_index]['materials'][slot][field]:
                        raise ValueError('Faux/BSP material identity differs')
                if materials[slot]['render method']['value'][1].replace('\\', '/') != target.rsplit('.', 1)[0]:
                    raise ValueError('Native row is aliased by another shader')
            source = [dict(material_slot=b['source_material'], shader=b['source_shader'],
                lighting_index=bsp['materials'][b['source_material']]['source_lighting_index'],
                source_fields=bsp['materials'][b['source_material']]['lighting'],
                directional_approximation=bsp['materials'][b['source_material']].get('emissive_authoring')) for b in bindings]
            rows.append(dict(source_bsp_index=bsp['source_index'], source_bsp=bsp['source_tag'],
                source=source, target_shader=target, native_material_info_index=index,
                native_material_slots=native_slots, native_fields=n, gr2_meshes=matched,
                unique_exported_triangle_count=sum(m['triangles'] for m in matched), status='MATCH'))
        expected_variants = {(i,j) for i,m in enumerate(exported['meshes']) for j,v in enumerate(m['variants'])
                             if gr2_values(v)['emissive power'] > 0}
        if covered_variants != expected_variants:
            raise ValueError('Positive GR2 annotations are not fully accounted for')
    return dict(format='foundry.environment-emissive-path-audit', version=1, status='MATCH',
        unique_native_positive_rows=len(rows), source_material_slots=sum(len(r['source']) for r in rows), rows=rows,
        inputs=dict(plan=dict(path=str(args.plan),sha256=sha(args.plan)),
            baseline_report=dict(path=str(args.baseline_report),sha256=sha(args.baseline_report)),
            gr2_report=dict(path=str(args.gr2_report),sha256=sha(args.gr2_report)),
            helper=dict(path=str(args.helper),sha256=sha(args.helper)), captures=captures),
        limitations=['GR2 triangle counts do not expand repeated model placements.',
                    'Input identity and value agreement does not establish illumination or cache invalidation.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'baseline-report', 'baseline-capture', 'gr2-report', 'helper', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new audit output path')
    result = audit(args)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(result['status'], result['unique_native_positive_rows'], 'native rows;', result['source_material_slots'], 'source slots')
