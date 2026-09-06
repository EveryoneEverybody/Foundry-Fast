"""Synthetic scene tests using native Foundry collection and scenario orchestration."""
import ast
from contextlib import contextmanager
import importlib
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
NAME = 'scenario_reference_smoke'
package = ModuleType(NAME); package.__path__ = [str(ROOT)]; sys.modules[NAME] = package
for part in ('managed_blam', 'tools'):
    module = ModuleType(NAME + '.' + part); module.__path__ = [str(ROOT / part)]
    sys.modules[module.__name__] = module
utils = ModuleType(NAME + '.utils')
backend = ModuleType(NAME + '.tools.importer')
sys.modules[utils.__name__] = utils; sys.modules[backend.__name__] = backend

class SceneProps(bpy.types.PropertyGroup):
    scene_project: bpy.props.StringProperty(default='Omaha')
    scale: bpy.props.StringProperty(default='blender')
    forward_direction: bpy.props.StringProperty(default='x')
    asset_type: bpy.props.StringProperty(default='scenario')
    maintain_marker_axis: bpy.props.BoolProperty(default=False)
    is_main_scene: bpy.props.BoolProperty(default=False)
class ObjectProps(bpy.types.PropertyGroup):
    export_this: bpy.props.BoolProperty(default=True)
    marker_game_instance_tag_name: bpy.props.StringProperty()
    marker_game_instance_tag_variant_name: bpy.props.StringProperty()
    marker_instance: bpy.props.BoolProperty()
    marker_model_group: bpy.props.StringProperty()
class CollectionProps(bpy.types.PropertyGroup):
    type: bpy.props.StringProperty()
    game_object_path: bpy.props.StringProperty()
    game_object_variant: bpy.props.StringProperty()
for cls in (SceneProps, ObjectProps, CollectionProps): bpy.utils.register_class(cls)
bpy.types.Scene.nwo = bpy.props.PointerProperty(type=SceneProps)
bpy.types.Object.nwo = bpy.props.PointerProperty(type=ObjectProps)
bpy.types.Collection.nwo = bpy.props.PointerProperty(type=CollectionProps)
main = bpy.context.scene
main.nwo.is_main_scene = True
main.frame_set(42)
utils.get_scene_props = lambda: main.nwo
utils.get_export_props = lambda: SimpleNamespace()
utils.rotation_diff_from_forward = lambda a, b: math.pi / 2 if b == 'y' else 0.
utils.print_section = lambda message: print(message)
utils.print_warning = lambda message: print('WARNING', message)
utils.get_tags_path = lambda: 'D:/HREK/tags'
backend.utils = utils
backend.bpy = bpy
backend.Path = Path
backend.OBJECT_TAG_EXTS = {'.scenery', '.crate', '.biped', '.weapon'}
backend.deferred_ops = []
backend.RenderModelOverrideType = SimpleNamespace(campaign=0, multiplayer=1, mainmenu=2, firefight=3)
backend.DECORATOR_CLOUD_PROP = 'decorator_cloud'

# Run the existing collection copier and scenario loop without ManagedBlam.
source_tree = ast.parse((ROOT / 'tools/importer.py').read_text())
helpers = {'_remap_driver_targets', '_copy_collection_object', 'clone_collection_hierarchy',
           'remove_orphan_object_data', 'remove_collection_hierarchy', 'merge_collection'}
for node in source_tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in helpers:
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<native importer helper>', 'exec'), backend.__dict__)
importer_node = next(node for node in source_tree.body if isinstance(node, ast.ClassDef) and node.name == 'NWOImporter')
methods = {}
for name in ('import_scenarios', '_ensure_game_object_collection_cache', 'get_cached_game_object_collection',
             'cache_game_object_collection'):
    node = next(node for node in importer_node.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<native importer method>', 'exec'), backend.__dict__)
    methods[name] = backend.__dict__[name]

@contextmanager
def mover(root, file):
    yield SimpleNamespace(tag_path=file)
utils.TagImportMover = mover

class ScenarioTag:
    valid = True
    tag_path = SimpleNamespace(ShortName='synthetic')
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get_bsp_paths(self, *args): return []
    def get_sky_indices(self): return []
    def read_scenario_type(self): return 0
    def survival_mode(self): return False
    def objects_to_blender(self, collection, collision, indices):
        objects, poses = [], []
        for index, (tag, variant, pose) in enumerate([
            ('objects/rack.crate', 'default', None), ('objects/rack.crate', 'default', None),
            ('objects/rack.crate', 'other', None), ('objects/civilian.biped', 'default', True)]):
            ob = bpy.data.objects.new(f'placement_{index}', None); collection.objects.link(ob)
            ob.nwo.marker_game_instance_tag_name = tag
            ob.nwo.marker_game_instance_tag_variant_name = variant
            ob.location = (index * 20, 2, 1)
            ob['fixture_placement'] = True
            objects.append(ob); poses.append(pose)
        return objects, poses
backend.ScenarioTag = ScenarioTag

class ObjectTag:
    def functions_to_blender(self): return {'glow': ['health']}
backend.ObjectTag = ObjectTag
class ModelTag:
    def get_variant_regions_and_permutations(self, variant, state): return {('body', variant)}
backend.ModelTag = ModelTag

created_renders = []
class RenderModelTag:
    def _create_armature(self, collection):
        data = bpy.data.armatures.new('source rig')
        arm = bpy.data.objects.new('source rig', data); collection.objects.link(arm)
        bpy.context.view_layer.objects.active = arm; arm.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        root = data.edit_bones.new('root'); root.head=(0,0,0); root.tail=(0,1,0)
        child = data.edit_bones.new('child'); child.head=(0,1,0); child.tail=(0,2,0); child.parent=root
        bpy.ops.object.mode_set(mode='OBJECT')
        return arm
backend.RenderModelTag = RenderModelTag

material = bpy.data.materials.new('shared textured material'); material.use_nodes = True
image = bpy.data.images.new('source texture', width=2, height=2)
texture = material.node_tree.nodes.new('ShaderNodeTexImage'); texture.image=image
material.node_tree.nodes.new('ShaderNodeNormalMap')

class Importer:
    def __init__(self, context):
        self.context=context; self.scene=context.scene; self.scene_collection=context.scene.collection
        self.scene_nwo=utils.get_scene_props(); self.scene_nwo_export=utils.get_export_props()
        self.tags_dir='D:/HREK/tags'; self.corinth=False; self.build_control_rig=False
        self.tag_render=True; self.tag_markers=True; self.from_vert_normals=False
        self.apply_materials=True; self.prefix_setting='none'; self.tag_variant=''
        self.tag_zone_set=''; self.tag_scenario_import_objects=True
        self.tag_scenario_import_decals=False; self.tag_scenario_import_decorators=False
        self.tag_import_design=False; self.tag_bsp_render_only=True; self.tag_sky=''; self.setup_as_asset=False
        self.obs_for_props={}; self.game_object_collection_cache=None
    def import_render_model(self, file, collection, existing, permutations, skip_print=False, allow_control_rig=True):
        created_renders.append((file, tuple(sorted(permutations)), bpy.context.scene.name))
        child_collection = bpy.data.collections.new('render'); collection.children.link(child_collection)
        arm = RenderModelTag()._create_armature(child_collection)
        mesh = bpy.data.meshes.new('source mesh')
        mesh.from_pydata([(0,1,0),(1,1,0),(0,2,0)],[],[(0,1,2)])
        mesh.uv_layers.new(name='UVMap'); mesh.uv_layers[0].data.foreach_set('uv',[0,0,1,0,0,1])
        mesh.attributes.new('source_attribute', 'FLOAT', 'POINT').data.foreach_set('value',[0.1,0.2,0.3])
        mesh.polygons[0].use_smooth = True
        mesh.normals_split_custom_set([(0,0.6,0.8)] * 3)
        ob = bpy.data.objects.new('render piece', mesh); child_collection.objects.link(ob)
        ob.parent=arm
        group=ob.vertex_groups.new(name='child'); group.add([0,1,2],1,'REPLACE')
        modifier=ob.modifiers.new('skin','ARMATURE'); modifier.object=arm
        mesh.materials.append(material)
        marker=bpy.data.objects.new('socket',None); child_collection.objects.link(marker)
        marker.parent=arm; marker.parent_type='BONE'; marker.parent_bone='child'; marker.location=(2,0,0)
        marker.nwo.marker_model_group='socket'
        return [arm,ob,marker],arm
    def import_child_object(self, collection, arm, marker, tint):
        child_collection=bpy.data.collections.new('weapon'); collection.children.link(child_collection)
        perms=ModelTag().get_variant_regions_and_permutations('default',0)
        objects,child_arm=self.import_render_model('weapon.render_model',child_collection,None,perms)
        for ob in objects:
            if ob.type=='MESH':
                ob['Primary Color']=tint; ob['glow']=0.6
                self.obs_for_props[ob]=ObjectTag().functions_to_blender()
        def attach():
            constraint=child_arm.constraints.new('COPY_TRANSFORMS'); constraint.target=marker
        backend.deferred_ops.append(attach)
        return objects
    def import_object(self, paths, existing, pose=None):
        self.tag_variant=paths.nwo.marker_game_instance_tag_variant_name
        root=bpy.data.collections.new('source model'); self.scene_collection.children.link(root)
        perms=ModelTag().get_variant_regions_and_permutations(self.tag_variant,0)
        file='rack.render_model' if paths.nwo.marker_game_instance_tag_name.endswith('.crate') else 'civilian.render_model'
        objects,arm=self.import_render_model(file,root,None,perms)
        for ob in objects:
            if ob.type=='MESH':
                ob['Primary Color']=[0.1,0.2,0.3,1]; ob['glow']=0.5
                self.obs_for_props[ob]=ObjectTag().functions_to_blender()
        if pose:
            arm.pose.bones['child'].rotation_mode='QUATERNION'
            arm.pose.bones['child'].rotation_quaternion=Quaternion((0,0,1),math.pi/4)
        if file.startswith('rack'):
            self.import_child_object(root,arm,objects[-1],[1,0,0,1])
            self.import_child_object(root,arm,objects[-1],[0,1,0,1])
        return root
for name, method in methods.items(): setattr(Importer,name,method)
backend.NWOImporter=Importer

last_importer=None
last_objects=[]
expected={}
def setup_materials(context, importer, starting, objects, *args, **kwargs):
    # Snapshot expected posed geometry after queued attachments in static mode.
    context.view_layer.update()
    for root in importer._scenario_reference_session.roots:
        context.scene.collection.children.link(root)
        dg=context.evaluated_depsgraph_get()
        for ob in root.all_objects:
            if ob.type=='MESH':
                ev=ob.evaluated_get(dg)
                expected[ob.name]=[(ev.matrix_world @ v.co).copy() for v in ev.data.vertices]
        context.scene.collection.children.unlink(root)
backend.setup_materials=setup_materials
backend.draw_scenario_import_sections=lambda *a,**k:None
class NWO_Import(bpy.types.Operator):
    bl_idname='nwo.foundry_import'
    bl_label='Test original importer entry'
    tag_scenario_import_objects:bpy.props.BoolProperty(default=True)
    def execute(self, context):
        global last_importer,last_objects
        backend.deferred_ops=[]
        last_importer=Importer(context)
        last_objects=last_importer.import_scenarios(['test.scenario'],True,False)
        backend.setup_materials(context,last_importer,[],last_objects,True)
        for op in backend.deferred_ops:op()
        backend.deferred_ops=[]
        return {'FINISHED'}
class NWO_OT_ImportFromDrop(bpy.types.Operator):
    bl_idname='nwo.reference_drop_test'; bl_label='Test drop entry'
    def execute(self,context):return {'FINISHED'}
backend.NWO_Import=NWO_Import; backend.NWO_OT_ImportFromDrop=NWO_OT_ImportFromDrop
reference=importlib.import_module(NAME+'.scenario_reference')
reference.prepare()
for cls in (NWO_Import,NWO_OT_ImportFromDrop):bpy.utils.register_class(cls)
reference.register()
try:
    for operator in (bpy.ops.nwo.foundry_import, bpy.ops.nwo.reference_drop_test):
        properties = operator.get_rna_type().properties
        assert reference.PROPERTY in properties, tuple(properties.keys())
        assert not properties[reference.PROPERTY].default
    assert bpy.ops.nwo.foundry_import(tag_scenario_static_reference=False)=={'FINISHED'}
    live_objects=set(bpy.data.objects); live_rigs=set(bpy.data.armatures)
    assert live_rigs and not any(s.name.startswith('Foundry reference work') for s in bpy.data.scenes)
    assert last_importer._scenario_reference_session.counts['render cache hits'] == 3
    # Cached child rigs have independent data and no parent points into a template.
    arms=[ob for ob in bpy.data.objects if ob.type=='ARMATURE']
    assert len({ob.data for ob in arms})==len(arms)
    assert not any(c.name.startswith('Foundry render template') for c in bpy.data.collections)

    before_renders=len(created_renders)
    assert bpy.ops.nwo.foundry_import(tag_scenario_static_reference=True)=={'FINISHED'}
    session=last_importer._scenario_reference_session
    assert session.counts['render cache hits']==3
    assert len(created_renders)-before_renders==4
    assert all('Foundry reference work' in scene for _,_,scene in created_renders[before_renders:])
    assert live_objects.issubset(set(bpy.data.objects))
    assert live_rigs==set(bpy.data.armatures)
    assert all(row['status']=='static_snapshot' for row in session.results)
    assert len(session.results)==3
    snapshots=[ob for ob in bpy.data.objects if ob.get(reference.REFERENCE) and ob.type=='MESH']
    assert len(snapshots)==7
    assert len({tuple(ob['Primary Color']) for ob in snapshots})==3
    assert not any(s.name.startswith('Foundry reference work') for s in bpy.data.scenes)
    for ob in snapshots:
        assert ob.parent is None and not ob.modifiers and not ob.constraints and not ob.animation_data
        assert not ob.nwo.export_this and ob['reference_frame']==42
        assert ob.data.uv_layers.get('UVMap') and ob.data.attributes.get('source_attribute')
        assert ob.material_slots[0].material==material
        assert ob.data.has_custom_normals
        for vertex,wanted in zip(ob.data.vertices,expected[ob['reference_source_object']]):
            assert ((ob.matrix_world @ vertex.co)-wanted).length<1e-5
    placements=[ob for ob in bpy.data.objects if ob.get('fixture_placement') and ob.get(reference.REFERENCE)]
    assert len(placements)==4
    for ob in placements:
        assert not ob.nwo.export_this
        assert ob.instance_collection.nwo.type=='exclude'
        assert not ob.instance_collection.nwo.game_object_path
    assert placements[0].instance_collection==placements[1].instance_collection
    assert placements[0].instance_collection!=placements[2].instance_collection
    assert not backend.deferred_ops
    assert not reference._runs and not reference._scopes and not reference._settings

    # Failure while preparing the second mesh leaves the original hierarchy intact.
    scratch=reference.Session(last_importer,True)
    with scratch.isolated():
        root=bpy.data.collections.new('rollback fixture');bpy.context.scene.collection.children.link(root)
        original_render=next(original for owner,name,original in reference._originals if owner is Importer and name=='import_render_model')
        first,_=original_render(last_importer,'rollback_a',root,None,set())
        second,_=original_render(last_importer,'rollback_b',root,None,set())
        objects=list(root.all_objects); bindings=[(ob,ob.parent,ob.data) for ob in objects]
        before_objects=set(bpy.data.objects);before_meshes=set(bpy.data.meshes)
        mesh_snapshot=reference._mesh_snapshot
        count=0
        def fail_second(*args):
            global count
            count+=1
            if count==2:raise RuntimeError('synthetic snapshot failure')
            return mesh_snapshot(*args)
        reference._mesh_snapshot=fail_second
        try:
            reference.freeze_collection(root,bpy.context,objects,last_importer)
            raise AssertionError('Expected snapshot failure')
        except RuntimeError as exc:assert str(exc)=='synthetic snapshot failure'
        finally:reference._mesh_snapshot=mesh_snapshot
        assert set(bpy.data.objects)==before_objects and set(bpy.data.meshes)==before_meshes
        assert all((ob.parent,ob.data)==(parent,data) for ob,parent,data in bindings)
        extra=bpy.data.objects.new('external target',None);main.collection.objects.link(extra)
        first[0].constraints.new('COPY_TRANSFORMS').target=extra
        try:
            reference.freeze_collection(root,bpy.context,objects,last_importer)
            raise AssertionError('Expected external dependency fallback')
        except ValueError as exc:assert 'External constraint' in str(exc)
    scratch.close()
    # Save/reopen with the work scene and render templates already removed.
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        names=[ob.name for ob in snapshots]
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(folder)/'references.blend'))
        bpy.ops.wm.open_mainfile(filepath=str(Path(folder)/'references.blend'))
        for name in names:
            ob=bpy.data.objects[name]
            assert ob.get(reference.REFERENCE) and not ob.nwo.export_this
            assert not ob.modifiers and ob.parent is None
            assert ob.data.uv_layers.get('UVMap') and ob.data.has_custom_normals
        assert not any(s.name.startswith('Foundry reference work') for s in bpy.data.scenes)
finally:
    reference.unregister()
    for cls in (NWO_OT_ImportFromDrop,NWO_Import):bpy.utils.unregister_class(cls)
print('Scenario reference tests passed: native scenario loop and collection cloning, render reuse, independent rigs, isolated construction, static poses, children, colors, UVs, normals, exclusions, cache separation, rollback and persistence')
