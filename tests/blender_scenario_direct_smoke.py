"""Direct-reference dispatch, function reuse, UI placement, and rest-matrix checks."""
from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
NAME = 'scenario_direct_smoke'
package = ModuleType(NAME); package.__path__ = [str(ROOT)]; sys.modules[NAME] = package
tools = ModuleType(NAME + '.tools'); tools.__path__ = [str(ROOT / 'tools')]; sys.modules[tools.__name__] = tools
managed = ModuleType(NAME + '.managed_blam'); managed.__path__ = [str(ROOT / 'managed_blam')]; sys.modules[managed.__name__] = managed
backend = ModuleType(NAME + '.tools.importer'); sys.modules[backend.__name__] = backend

class ObjectProps(bpy.types.PropertyGroup):
    export_this: bpy.props.BoolProperty(default=True)
    marker_game_instance_tag_name: bpy.props.StringProperty()
    marker_game_instance_tag_variant_name: bpy.props.StringProperty()
class CollectionProps(bpy.types.PropertyGroup):
    type: bpy.props.StringProperty()
for cls in (ObjectProps, CollectionProps): bpy.utils.register_class(cls)
bpy.types.Object.nwo = bpy.props.PointerProperty(type=ObjectProps)
bpy.types.Collection.nwo = bpy.props.PointerProperty(type=CollectionProps)

class Session:
    def __init__(self):
        self.enabled=True; self.depth=1; self.object_depth=0; self.counts={}; self.results=[]; self.slowest=[]
    @contextmanager
    def isolated(self): yield bpy.context.scene
    def report(self): pass
    def time(self, label):
        @contextmanager
        def cm(): yield
        return cm()
session=Session()
reference=ModuleType(NAME+'.scenario_reference')
reference.PROPERTY='tag_scenario_static_reference'; reference.REFERENCE='foundry_static_reference'; reference._scopes=[session]
reference._session=lambda importer:session
reference.Session=Session
sys.modules[reference.__name__]=reference

utils=ModuleType(NAME+'.utils'); sys.modules[utils.__name__]=utils

# Stubs let the real direct module load so its matrix helper is exercised.
import_transform=ModuleType(NAME+'.managed_blam.import_transform')
def armature_bone_matrix(matrix, scene_nwo, root=False):
    result=matrix.copy(); result.translation*=scene_nwo.factor
    if root: result=Matrix.Rotation(scene_nwo.rotation,4,'Z') @ result
    return result
import_transform.armature_bone_matrix=armature_bone_matrix
sys.modules[import_transform.__name__]=import_transform
connected=ModuleType(NAME+'.managed_blam.connected_geometry')
for name in ('CompressionBounds','Material','Mesh','Node','Region'):
    setattr(connected,name,type(name,(),{}))
sys.modules[connected.__name__]=connected

live_calls=[]
class Importer:
    def __init__(self): self.scene_collection=bpy.context.scene.collection; self.scene=bpy.context.scene
    def import_object(self, paths, existing_armature, pose=None, *args, **kwargs):
        live_calls.append(paths.nwo.marker_game_instance_tag_name); return 'live'
backend.NWOImporter=Importer
class ObjectTag:
    calls=0
    def __init__(self, path='objects/test.scenery'):
        self.tag_path=SimpleNamespace(RelativePathWithExtension=path)
    def functions_to_blender(self):
        ObjectTag.calls+=1; return {'glow':['health']}
backend.ObjectTag=ObjectTag
backend.draw_import_template=lambda *a,**k:None
backend.remove_collection_hierarchy=lambda c:None

# Direct dispatcher stub: one rigid object succeeds, biped deliberately falls back.
direct=ModuleType(NAME+'.scenario_static_direct')
def try_build(importer, placement, pose, current_session):
    if placement.nwo.marker_game_instance_tag_name.endswith('.biped'):
        return None,'skinned render geometry needs the live reference path'
    root=bpy.data.collections.new('direct root'); importer.scene_collection.children.link(root)
    mesh=bpy.data.meshes.new('direct mesh'); mesh.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
    ob=bpy.data.objects.new('direct mesh',mesh); root.objects.link(ob); root['reference_variant']='default'
    return root,None
direct.try_build=try_build
sys.modules[direct.__name__]=direct

patch=importlib.import_module(NAME+'.scenario_reference_direct_patch')

class Box:
    def __init__(self, log, label='root'): self.log=log; self.box_label=label; self.enabled=True
    def box(self): return Box(self.log,'unlabelled')
    def label(self, text=''): self.box_label=text
    def prop(self, operator, name, **kwargs): self.log.append((self.box_label,name))
    def row(self): return Box(self.log,self.box_label)
    def column(self, **kwargs): return Box(self.log,self.box_label)

class Operator:
    tag_zone_set=''; tag_bsp_import_geometry=True; tag_import_lights=True; setup_as_asset=False
    force_no_setup_as_asset=False; tag_bsp_render_only=True; tag_bsp_skip_structure_merge=False
    tag_import_design=False; tag_sky=''; tag_scenario_import_objects=True
    tag_scenario_static_reference=True; tag_scenario_import_decals=False; tag_scenario_import_decorators=False
    decorator_lod='1'; build_blender_materials=True; always_extract_bitmaps=False

patch.register()
try:
    log=[]
    backend.draw_scenario_import_sections(Operator(),Box(log),False,show_template=False,show_scenario_content=True,show_setup_as_asset=False)
    viewing=[name for box,name in log if box=='Blender Viewing']
    assert reference.PROPERTY in viewing
    assert viewing.index(reference.PROPERTY)==viewing.index('tag_scenario_import_objects')+1

    importer=Importer()
    rigid=bpy.data.objects.new('rigid placement',None); bpy.context.scene.collection.objects.link(rigid)
    rigid.nwo.marker_game_instance_tag_name='objects/rigid.scenery'; rigid.nwo.marker_game_instance_tag_variant_name='default'
    result=importer.import_object(rigid,None)
    assert isinstance(result,bpy.types.Collection) and result.get(reference.REFERENCE)
    assert not live_calls and session.counts['direct static definitions']==1
    assert session.results[-1]['status']=='direct_static'
    assert all(not ob.nwo.export_this for ob in result.all_objects)

    biped=bpy.data.objects.new('biped placement',None); bpy.context.scene.collection.objects.link(biped)
    biped.nwo.marker_game_instance_tag_name='objects/civilian.biped'
    assert importer.import_object(biped,None)=='live'
    assert live_calls==['objects/civilian.biped']
    assert session.counts['direct static fallbacks']==1

    tag=ObjectTag('objects/shared.weapon')
    assert tag.functions_to_blender()=={'glow':['health']}
    assert tag.functions_to_blender()=={'glow':['health']}
    assert ObjectTag.calls==1
    assert session.counts['object function cache hits']==1

    # Direct node matrices match the armature convention without a Blender armature.
    actual_direct=importlib.import_module(NAME+'.scenario_static_direct')
    root=SimpleNamespace(index=0,name='root',parent=None,translation=Vector((100,0,0)),rotation=Quaternion((1,0,0,0)))
    child=SimpleNamespace(index=1,name='child',parent=root,translation=Vector((0,100,0)),rotation=Quaternion((1,0,0,0)))
    matrices=actual_direct._node_world_matrices([root,child],SimpleNamespace(factor=0.03048,rotation=0.0))
    assert (matrices[0].translation-Vector((3.048,0,0))).length<1e-6
    assert (matrices[1].translation-Vector((3.048,3.048,0))).length<1e-6
finally:
    patch.unregister()

print('Scenario direct checks passed: Blender Viewing placement, direct dispatch, live fallback, function reuse and node transforms')
