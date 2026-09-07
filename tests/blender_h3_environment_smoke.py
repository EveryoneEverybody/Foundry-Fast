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
    # Exercise the actual texture exporter with asymmetric synthetic cube
    # faces. No game pixels are needed to catch AgX color transforms or a
    # changed axis/rotation during native source-atlas authoring.
    import numpy as np
    from io_scene_foundry.tools.export_bitmaps import save_image_as
    from port_environment.native_bitmaps import author_cube,REACH_CELLS
    cells=((0,1),(2,1),(1,0),(1,2),(1,1),(3,1))
    original=np.zeros((12,16,4),dtype=np.float32)
    for face,(x,y) in enumerate(cells):
        for py in range(4):
            for px in range(4):
                original[y*4+py,x*4+px]=[(face+1)/8,(px+1)/5,(py+1)/5,1]
    source=bpy.data.images.new('synthetic cube',width=16,height=12,alpha=True)
    source.colorspace_settings.name='sRGB';source.alpha_mode='CHANNEL_PACKED'
    source.pixels.foreach_set(np.ascontiguousarray(original[::-1]).ravel())
    cube=author_cube(source,dict(layout='directx_cross_4x3',
        face_order=['+X','-X','+Y','-Y','+Z','-Z'],cells=cells))
    filename=save_image_as(cube,paths.roots['data'],tiff_name='synthetic_cube.tif')
    read=bpy.data.images.load(str(paths.roots['data']/filename),check_existing=False)
    read.colorspace_settings.name='Non-Color'
    pixels=np.empty(16*12*4,dtype=np.float32);read.pixels.foreach_get(pixels)
    actual=pixels.reshape(12,16,4)[::-1]
    for (sx,sy),(dx,dy) in zip(cells,REACH_CELLS):
        np.testing.assert_allclose(actual[dy*4:(dy+1)*4,dx*4:(dx+1)*4],
            original[sy*4:(sy+1)*4,sx*4:(sx+1)*4],atol=1/255)
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
