"""Numerical Blender tests with synthetic clips and real Scarab rest metadata.

No H3EK payload decode, Reach Tool compilation, or in-game validation.
"""
import copy
import importlib
import json
import math
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import bpy
from bpy_extras import anim_utils
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).parent))
from h3_animation_fixture import payload, scarab_metadata
ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
NAME = 'foundry_animation_smoke'
package = ModuleType(NAME); package.__path__ = [str(ROOT)]; sys.modules[NAME] = package
settings = SimpleNamespace(scale='blender', forward_direction='x', export_in_progress=False,
                           node_usage_pose_blend_pitch='', node_usage_pose_blend_yaw='')
utils = ModuleType(NAME + '.utils')
utils.get_scene_props = lambda: settings
utils.rotation_diff_from_forward = lambda start,end: math.pi/2 if end == 'y' else 0.
utils.remove_node_prefix = lambda name: name[2:] if name.startswith('b_') else name
utils.get_fcurves = lambda action,slot: anim_utils.action_ensure_channelbag_for_slot(action,slot).fcurves
utils.current_project_valid = lambda: True
utils.is_corinth = lambda context: False
sys.modules[NAME + '.utils'] = utils
for part in ('managed_blam','h3_import'):
    m=ModuleType(NAME+'.'+part);m.__path__=[str(ROOT/part)];sys.modules[m.__name__]=m

class Track(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object)
    action: bpy.props.PointerProperty(type=bpy.types.Action)
class Animation(bpy.types.PropertyGroup):
    frame_start: bpy.props.IntProperty(default=1)
    frame_end: bpy.props.IntProperty(default=30)
    animation_type: bpy.props.StringProperty()
    animation_movement_data: bpy.props.StringProperty()
    export_this: bpy.props.BoolProperty(default=True)
    action_tracks: bpy.props.CollectionProperty(type=Track)
class SceneProps(bpy.types.PropertyGroup):
    animations: bpy.props.CollectionProperty(type=Animation)
class ObjProps(bpy.types.PropertyGroup):
    node_order_source: bpy.props.StringProperty()
    export_this: bpy.props.BoolProperty(default=True)
class CollProps(bpy.types.PropertyGroup):
    type: bpy.props.StringProperty()
for cls in (Track,Animation,SceneProps,ObjProps,CollProps):bpy.utils.register_class(cls)
bpy.types.Scene.test_nwo=bpy.props.PointerProperty(type=SceneProps)
bpy.types.Object.nwo=bpy.props.PointerProperty(type=ObjProps)
bpy.types.Collection.nwo=bpy.props.PointerProperty(type=CollProps)
settings.animations=bpy.context.scene.test_nwo.animations
A=importlib.import_module(NAME+'.h3_import.animations')
B=importlib.import_module(NAME+'.h3_import.animation_builder')


def matrix(n):
    r=n['rest'];return Matrix.LocRotScale(Vector(r['position']),Quaternion(r['rotation']),Vector.Fill(3,r['scale']))


def object_space(nodes, local):
    result=[]
    for i,n in enumerate(nodes):result.append(local[i] if n['parent']<0 else result[n['parent']]@local[i])
    return result


def converted(m):
    p=m.copy();p.translation*=100*(0.03048 if settings.scale=='blender' else 1)
    return Matrix.Rotation(math.pi/2 if settings.forward_direction=='y' else 0,4,'Z')@p


def near(a,b,tol=0.003):
    error=max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))
    assert error<tol,(error,a,b)


def rig(nodes):
    arm_data=bpy.data.armatures.new('test source');arm=bpy.data.objects.new('test source',arm_data)
    bpy.context.scene.collection.objects.link(arm);bpy.context.view_layer.objects.active=arm;arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    rest=object_space(nodes,[matrix(n) for n in nodes])
    for n in nodes:
        b=arm_data.edit_bones.new(n['name']);b.head=(0,0,0);b.tail=(0,0.1,0)
    for i,n in enumerate(nodes):
        b=arm_data.edit_bones[n['name']]
        if n['parent']>=0:b.parent=arm_data.edit_bones[nodes[n['parent']]['name']]
        b.matrix=converted(rest[i]);b.use_deform=True
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh=bpy.data.meshes.new('weighted triangle');mesh.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
    ob=bpy.data.objects.new('weighted triangle',mesh);bpy.context.scene.collection.objects.link(ob)
    ob.parent=arm;g=ob.vertex_groups.new(name=nodes[-1]['name']);g.add([0,1,2],1,'REPLACE')
    mod=ob.modifiers.new('source skin','ARMATURE');mod.object=arm
    arm.animation_data_create();keep=bpy.data.actions.new('source untouched');keep.use_fake_user=True
    slot=keep.slots.new('OBJECT',arm.name);arm.animation_data.action=keep;arm.animation_data.action_slot=slot
    return arm,ob,keep


def write_jma(path,nodes,frames):
    children={i:[] for i in range(len(nodes))}
    for i,n in enumerate(nodes):
        if n['parent']>=0:children[n['parent']].append(i)
    lines=['16392',str(len(frames)),'30','1','actor',str(len(nodes)),'0']
    for i,n in enumerate(nodes):
        sib=children.get(n['parent'],[])
        nxt=sib[sib.index(i)+1] if i in sib and sib.index(i)+1<len(sib) else -1
        lines += [n['name'],str(children[i][0] if children[i] else -1),str(nxt)]
    for frame in frames:
        for m in frame:
            p,q,s=m.decompose();p*=100;q.conjugate()
            lines += [' '.join(map(str,p)),' '.join(map(str,(*q[1:],q[0]))),str(s[0])]
    path.write_text('\n'.join(lines)+'\n')


def snapshot():
    return tuple(len(s) for s in (bpy.data.objects,bpy.data.meshes,bpy.data.armatures,bpy.data.actions,bpy.data.collections,bpy.data.texts))+ (len(settings.animations),)


fixture=scarab_metadata()
for target_native,scale,forward in [(False,'blender','x'),(True,'blender','x'),(True,'blender','y'),(True,'max','x')]:
    settings.scale,settings.forward_direction=scale,forward
    source_nodes=fixture['source_nodes'];target_nodes=fixture['target_nodes'] if target_native else source_nodes
    arm,mesh,keep=rig(target_nodes)
    original_matrices={p.name:p.matrix_basis.copy() for p in arm.pose.bones}
    original_bones=list(arm.data.bones.keys());source_action=arm.animation_data.action
    before=snapshot()
    p=payload();p['nodes']=copy.deepcopy(source_nodes);p['animations']=[]
    expected=[]
    with tempfile.TemporaryDirectory() as folder:
        folder=Path(folder)
        for idx,kind in enumerate(('JMM','JMA','JMT')):
            frame_info={'JMM':'none','JMA':'dx,dy','JMT':'dx,dy,dyaw'}[kind]
            name=['combat:idle','combat:move_front','combat:move_front_left'][idx]
            rest=[matrix(n) for n in source_nodes]
            locals_,motions=[],[]
            for f in range(3):
                motion=Matrix.Identity(4)
                if kind!='JMM':
                    motion=Matrix.Translation((f,0.25*f,0))@Matrix.Rotation(f*0.25 if kind=='JMT' else 0,4,'Z')
                frame=[m.copy() for m in rest]
                frame[1]=frame[1]@Matrix.Rotation(min(f,1)*0.1,4,'Y')
                # Mirror the decoder's root translation-add and rotation composition.
                loc,rot,sca=frame[0].decompose()
                loc+=motion.translation;rot=motion.to_quaternion()@rot
                frame[0]=Matrix.LocRotScale(loc,rot,sca)
                locals_.append(frame);motions.append([motion])
            d={'kind':kind,'jma_file':f'clip{idx}.{kind.lower()}', 'motion_file':None if kind=='JMM' else f'motion{idx}.{kind.lower()}',
               'decoded_frame_count':2,'file_frame_count':3,'fps':30,'frame_layout':'codec_frames_then_held_terminal'}
            clip={'name':name,'index':idx,'status':'decoded','source_node_count':33,'source_frame_count':2,
                  'animation_type':'base','frame_info_type':frame_info,'world_relative':False,'decoded':d}
            p['animations'].append(clip)
            write_jma(folder/d['jma_file'],source_nodes,locals_)
            if d['motion_file']:write_jma(folder/d['motion_file'],[{'name':'movement','parent':-1}],motions)
            expected.append((locals_,motions))
        p['animations'].append({'name':'combat:buckle_wobble','index':99,'status':'unsupported','message':'overlay retained'})
        A.validate_manifest(p)
        stage=B.AnimationStager(bpy.context,p,folder,arm)
        list(stage.build())
        assert len(stage.mapping)==33
        assert len(stage.armature.data.bones)==(47 if target_native else 34)
        assert stage.collection.nwo.type=='exclude'
        assert all(not row.export_this for row in stage.animations)
        assert [row.animation_movement_data for row in stage.animations]==['none','xy','xyyaw']
        assert list(arm.data.bones.keys())==original_bones
        assert arm.animation_data.action==source_action
        for pb in arm.pose.bones:near(pb.matrix_basis,original_matrices[pb.name])
        for clip_idx,row in enumerate(stage.animations):
            action=row.action_tracks[0].action
            stage.armature.animation_data.action=action;stage.armature.animation_data.action_slot=action.slots[0]
            for f in range(3):
                bpy.context.scene.frame_set(f+1);bpy.context.view_layer.update()
                local,motions=expected[clip_idx]
                worlds=object_space(source_nodes,local[f])
                for n,world in zip(source_nodes,worlds):
                    near(stage.armature.pose.bones[stage.mapping[n['name']]].matrix,converted(world),0.02 if scale=='max' else 0.003)
                near(stage.armature.pose.bones[stage.pedestal].matrix,converted(motions[f][0]),0.02 if scale=='max' else 0.003)
                for b in stage.armature.data.bones:
                    if b.name.endswith('_atr_u'):
                        near(stage.armature.pose.bones[b.name].matrix,
                             stage.armature.pose.bones[b.parent.name].matrix@stage.rest_local[b.name],0.02 if scale=='max' else 0.003)
        assert any(r['status']=='unsupported' for r in stage.results)
        # Removing extraction files must not remove the staged keyframes.
        for file in folder.iterdir():file.unlink()
        stage.rollback();assert snapshot()==before,(snapshot(),before)
    bpy.data.objects.remove(mesh,do_unlink=True);bpy.data.objects.remove(arm,do_unlink=True)

# Failure after copying the rig must be reversible.
settings.scale,settings.forward_direction='blender','x'
arm,ob,keep=rig(fixture['target_nodes']);p=payload();p['nodes']=copy.deepcopy(fixture['source_nodes'])
p['nodes'][1]['rest']['position'][0]+=1
before=snapshot();stage=B.AnimationStager(bpy.context,p,Path('.'),arm)
try:stage.stage_rig();raise AssertionError('Expected rest-pose rejection')
except ValueError as exc:assert 'bind pose' in str(exc)
stage.rollback();assert snapshot()==before
print('H3 animation Blender tests passed: 33-to-47 mapping, JMA parsing, idle/XY/yaw motion, pedestal separation, extra bones, source preservation, rollback, both scene scales and orientation')
