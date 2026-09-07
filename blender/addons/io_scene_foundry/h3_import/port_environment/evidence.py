"""Hash and inspect user-supplied authoring oracles without executing their contents."""
import hashlib
from pathlib import Path
from zipfile import ZipFile

from . import fixtures
from .paths import digest, relative


def inspect_archive(path, members):
    path=Path(path).resolve(strict=True)
    result=dict(path=str(path),sha256=digest(path),members={},policy='Authoring evidence only; no geometry copied and no scripts executed')
    with ZipFile(path) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Duplicate authoring-oracle archive member')
        for name in members:
            relative(name)
            info=z.getinfo(name)
            if info.file_size>32*1024*1024:
                raise ValueError('Oversized selected authoring-oracle member')
            raw=z.read(name)
            row=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            if name.endswith('.xml'):
                root=fixtures.parse(raw)
                row.update(group=root.get('group'),source_id=root.get('id'),
                           field_names=sorted({e.get('name') for e in root.iter('field') if e.get('name')}))
            result['members'][name]=row
    return result


def archives(args):
    result={}
    if args.h3_xml_evidence:
        result['h3']=inspect_archive(args.h3_xml_evidence,[
            'H3TagXML/levels/solo/040_voi/040_voi_040_design.structure_design.xml',
            'H3TagXML/levels/solo/040_voi/040_bsp_040.scenario_structure_lighting_info.xml',
            'H3TagXML/levels/solo/040_voi/lights/factory_arm_blue_a.light.xml',
            'H3TagXML/levels/solo/040_voi/shaders/natural/lakebed.shader_terrain.xml'])
    if args.reach_xml_evidence:
        result['reach']=inspect_archive(args.reach_xml_evidence,[
            'ReachTagXML/levels/solo/m20/m20_soft_ceiling.structure_design.xml',
            'ReachTagXML/levels/reference/lighting_reference/outside.scenario_structure_lighting_info.xml',
            'ReachTagXML/objects/levels/solo/m20/oni_floorscanner/oni_floorscanner_light.light.xml',
            'ReachTagXML/levels/reference/lighting_reference/shaders/terrain_grass.shader_terrain.xml'])
    if args.templates:
        result['templates']=inspect_archive(args.templates,['templates/'+name for name in (
            'scenario_scenario_structure_bsp.gr2','sky_render_model.blend','sky_render_model.fbx',
            'sky_render_model.GR2','generate_gr2_to_json_examples.py')])
    return result
