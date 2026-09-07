"""Actual registered Foundry geometry semantics; no ManagedBlam/Tool mocks."""
from pathlib import Path
import sys
import tempfile

import bpy

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'blender/addons'))
bpy.ops.preferences.addon_enable(module='io_scene_foundry')
sys.path.insert(0,str(root/'tests'))
from test_h3_environment import inputs, roots
from port_environment.model import construct
from port_environment.worker import setup_scene, mesh_object
from io_scene_foundry import utils

with tempfile.TemporaryDirectory() as directory:
    paths = roots(directory)
    plan = construct(paths,*inputs(paths))
    prefs = utils.get_prefs()
    prefs.projects.clear()
    project = prefs.projects.add()
    project.name='Proof geometry test'
    project.project_path=str(paths.reach)
    project.tags_directory=str(paths.roots['tags'])
    project.data_directory=str(paths.roots['data'])
    scene = setup_scene('proof','scenario',paths.scenario+'.sidecar.xml','proof_box_bsp',project.name)
    materials = [bpy.data.materials.new('synthetic render'),bpy.data.materials.new('synthetic collision')]
    for record in plan['bsp']['meshes']:
        ob,stats=mesh_object(record,materials,scene,'proof_box_bsp',record['name'],record['role'])
        assert ob.nwo.export_this
        assert ob.data.nwo.mesh_type=='_connected_geometry_mesh_type_structure'
        assert ob.data.nwo.face_props[0].face_mode==record['face_mode']
        # Export consolidates real face attributes; a property with no mask and
        # face_count=0 is discarded even if the UI's get_all_faces reports true.
        utils.consolidate_face_attributes(ob.data)
        assert ob.data.nwo.face_props[0].face_count==len(ob.data.polygons)
        attr=ob.data.attributes[ob.data.nwo.face_props[0].attribute_name]
        assert all(v.value for v in attr.data)
        assert ob.data.polygons[0].material_index==record['triangles'][0]['material']
        assert stats['triangles']==1 and stats['vertices']==3
        assert stats['maximum_coordinate_rounding_ass']==0
    assert utils.get_scene_props().scale=='max' and utils.get_scene_props().forward_direction=='x'
    assert utils.get_scene_props().regions_table[0].name=='proof_box_bsp'
    assert utils.get_export_props().event_level=='DEFAULT'
    assert not utils.get_export_props().lightmap_structure
    assert not list(paths.roots['tags'].rglob('*')), 'Geometry test must not write tags'
# Unit-test the real shared Reach orchestration's command decisions. No Tool
# result is simulated as native acceptance; only dispatch and early aborts are
# examined here. Native Tool/Faux acceptance remains the Windows local runner.
from unittest.mock import patch
from io_scene_foundry.tools.scenario import lightmap
for quality,expected in [('direct_only',['dillum']),('draft',['dillum','pcast','radest_extillum','fgather']),
                         ('high',['dillum','pcast','radest_extillum','fgather'])]:
    for fail in (None,'dillum'):
        driver=object.__new__(lightmap.LightMapper)
        driver.scenario='levels/h3_port/proof_box/proof_box'
        driver.bsp='all';driver.quality=quality;driver.light_group=''
        commands,farms=[],[]
        def run(command,stage,**kwargs):
            commands.append(stage)
            return True
        def farm(stage):
            farms.append(stage)
            return stage!=fail
        driver.run_tool_or_abort=run
        driver.farm=farm
        with patch.object(lightmap,'ToolPatcher') as patcher, patch.object(lightmap.utils,'get_project_path',return_value=tempfile.gettempdir()):
            patcher.return_value.reach_lightmap_color.return_value=[]
            driver.lightmap_reach()
        assert farms == (expected if fail is None else ['dillum'])
        assert ('faux_farm_finish' in commands)==(fail is None)
        assert commands[:2]==['faux_data_sync','faux_farm_begin']
print('H3 environment construction and Reach lightmap command regression passed',flush=True)
