"""Terrain albedo pixels and BSP-slot diagnostics, including constant grey."""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import bpy

base=runpy.run_path(str(Path(__file__).with_name('blender_h3_scenario_smoke.py')))
from h3_material_fixture import manifest
from h3_scenario_fixture import bsp,scene,inventory
Session=base['mod'].ScenarioBuildSession
SHADER='levels/solo/fixture/shaders/lakebed.shader_terrain'

with tempfile.TemporaryDirectory() as d:
    directory=Path(d);(directory/'textures').mkdir()
    colors=[(.2,.3,.1,.8),(1.,0.,0.,1.),(0.,1.,0.,1.),(0.,0.,1.,1.)]
    data=manifest();shader=data['shaders'].pop('objects/test/test.shader');data['shaders'][SHADER]=shader
    shader.update(source=SHADER,group='rmtr',parameters=[],categories=[dict(category='blending',option='morph')]+[dict(category=f'material_{i}',option='diffuse_only' if i<3 else 'off') for i in range(4)])
    data['bitmaps']={}
    for i,color in enumerate(colors):
        image=bpy.data.images.new('Terrain fixture',width=4,height=4,alpha=True,float_buffer=True)
        image.colorspace_settings.name='Non-Color';image.alpha_mode='CHANNEL_PACKED';image.pixels[:]=list(color)*16
        image.filepath_raw=str(directory/f'textures/{i}.tif');image.file_format='TIFF';image.save();bpy.data.images.remove(image)
        key=f'textures/{i}#0'
        data['bitmaps'][key]=dict(path=f'textures/{i}',index=0,curve='Linear',preview=f'textures/{i}.tif',status='preview',width=4,height=4,depth=1,type='2D texture')
        shader['parameters'].append(dict(name='blend_map' if i==0 else f'base_map_m_{i-1}',type='bitmap',bitmap=key,transform=[1,1,0,0],sampler=dict(filter='linear',address_x='wrap',address_y='wrap')))
    shader['parameters'] += [dict(name='global_albedo_tint',type='real',value=1.),dict(name='dynamic_material',type='color',value=[0,1,0,0]),dict(name='transition_threshold',type='real',value=.3),dict(name='transition_sharpness',type='real',value=1.)]
    session=Session(bpy.context,scene(),inventory(),directory,data)
    session.root=session.collection('Material test',bpy.context.scene.collection)
    session.shader_source=session.text('Shader source',data)
    for ob in list(bpy.data.objects):bpy.data.objects.remove(ob,do_unlink=True)
    bpy.ops.mesh.primitive_plane_add(size=4);plane=bpy.context.object
    bpy.ops.object.camera_add(location=(0,0,2));camera=bpy.context.object;camera.data.type='ORTHO';camera.data.ortho_scale=2
    settings=bpy.context.scene;settings.camera=camera;settings.render.engine='CYCLES';settings.cycles.device='CPU';settings.cycles.samples=4;settings.cycles.use_denoising=False
    settings.render.resolution_x=settings.render.resolution_y=16;settings.render.resolution_percentage=100
    settings.render.image_settings.file_format='OPEN_EXR';settings.render.image_settings.color_depth='32'
    for mode in ('morph','dynamic_morph'):
        shader['categories'][0]['option']=mode
        record=bsp()['materials'][0];record['source_shader']=SHADER
        mat=session.material(record,bsp(),0,17)
        assert mat['h3_material_preview']=='approximate_preview',json.loads(mat['h3_material_diagnostics'])
        nodes=mat.node_tree.nodes;surface=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
        assert surface.inputs['Base Color'].is_linked
        blend=next(n for n in nodes if n.label=='blend_map')
        assert blend.image.colorspace_settings.name=='Non-Color' and blend.image.packed_file
        assert all(next(n for n in nodes if n.label==f'base_map_m_{i}').outputs['Color'].is_linked for i in range(3))
        # Route the production albedo output to emission to measure it without lighting.
        emission=nodes.new('ShaderNodeEmission');mat.node_tree.links.new(surface.inputs['Base Color'].links[0].from_socket,emission.inputs['Color'])
        output=next(n for n in nodes if n.type=='OUTPUT_MATERIAL');mat.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
        plane.data.materials.clear();plane.data.materials.append(mat)
        weights=list(blend.image.pixels[:4]);alpha=max(0,min(1,(weights[3]-.3)))
        if mode=='dynamic_morph':weights=[weights[0]*(1-alpha),weights[1]*(1-alpha)+alpha,weights[2]*(1-alpha)]
        expected=[v/sum(weights[:3]) for v in weights[:3]]
        settings.render.filepath=str(directory/(mode+'.exr'));bpy.ops.render.render(write_still=True)
        rendered=bpy.data.images.load(settings.render.filepath,check_existing=False);actual=list(rendered.pixels[(8*16+8)*4:(8*16+8)*4+3]);bpy.data.images.remove(rendered)
        assert max(abs(a-b) for a,b in zip(actual,expected))<.015,(mode,actual,expected)
        assert mat.nwo.shader_path=='' and mat['h3_source_shader']==SHADER
    # Missing bitmap remains identifiable by BSP, shader, slot and affected triangles.
    data['bitmaps'].clear();bad=session.material(record,bsp(),3,23)
    report=json.loads(bad['h3_bsp_material_diagnostics'])
    assert bad['h3_material_preview']=='placeholder'
    assert report['slot']==3 and report['source_triangle_count']==23 and report['source_shader']==SHADER
    assert {'bitmap_extraction','blender_preview'} <= {i['stage'] for i in report['issues']}
    # Constant-color grey needs no bitmap; preserve it in nodes and solid material color.
    gray=manifest()['shaders']['objects/test/test.shader'];gray['categories']=[dict(category='albedo',option='constant_color')]
    gray['parameters']=[dict(name='albedo_color',type='color',value=[.392156869]*3+[1.])]
    data['shaders']['objects/test/test.shader']=gray
    graymat=session.material(bsp()['materials'][0],bsp(),0,2)
    assert max(abs(c-.392156869) for c in graymat.diffuse_color[:3])<1e-6
    surface=next(n for n in graymat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    assert max(abs(c-.392156869) for c in surface.inputs['Base Color'].default_value[:3])<1e-6
print('H3 BSP material tests passed: numerical morph/dynamic terrain albedo, exact shader identity, missing bitmap diagnostics and constant grey')
