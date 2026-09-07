"""Readback of source-derived native lighting, before allowing Faux to run."""
import math
from pathlib import Path
from . import authoring


def close(actual, expected, label, tolerance=1e-4):
    a=list(actual) if hasattr(actual,'__iter__') else [actual]
    b=list(expected) if hasattr(expected,'__iter__') else [expected]
    if len(a)!=len(b) or any(not math.isfinite(float(x)) or
        abs(float(x)-float(y))>tolerance*max(1,abs(float(y))) for x,y in zip(a,b)):
        raise ValueError(f'Native authoring readback mismatch {label}: {a} != {b}')


def lighting(plan, report):
    from io_scene_foundry.managed_blam import Tag
    rows=[]
    for bsp,light in zip(plan['bsps'],plan['lighting_by_bsp']):
        path=bsp['destination'].rsplit('.',1)[0]+'.scenario_structure_lighting_info'
        with Tag(path=path,tag_must_exist=True) as tag:
            definitions=tag.tag.SelectField('Block:generic light definitions').Elements
            instances=tag.tag.SelectField('Block:generic light instances').Elements
            close(definitions.Count,len(light['definitions']),path+' definitions')
            close(instances.Count,len(light['instances']),path+' instances')
            for element,d in zip(definitions,light['definitions']):
                for field,key in [('type','type'),('color','color'),('intensity','intensity'),('aspect','aspect'),
                    ('near attenuation bounds','near_attenuation'),('far attenuation bounds','far_attenuation')]:
                    f=element.SelectField(field)
                    close(f.Value if field=='type' else f.Data,d[key],path+' '+field)
                close(element.SelectField('shape').Value,{'rectangle':0,'circle':1}[d['source_fields']['shape']],path+' shape')
                if d['type']==1:
                    for field,key in [('hotspot size','hotspot_size'),('hotspot cutoff size','hotspot_cutoff'),
                        ('hotspot falloff speed','hotspot_falloff')]:
                        close(element.SelectField(field).Data,d[key],path+' '+field)
                flags=element.SelectField('flags')
                actual_flags=sum(1<<i for i,item in enumerate(flags.Items) if item.IsSet)
                close(actual_flags,d['flags'],path+' named attenuation flags')
            for element,i in zip(instances,light['instances']):
                for field,key in [('definition index','definition_index'),('origin','origin'),('forward','forward'),('up','up')]:
                    close(element.SelectField(field).Data,i[key],path+' instance '+field)
            native_emission=[]
            for m in tag.tag.SelectField('Block:material info').Elements:
                native_emission.append({k:m.SelectField(k).Data for k in ('emissive power','emissive color',
                    'emissive focus','attenuation falloff','attenuation cutoff')})
        with Tag(path=bsp['destination'],tag_must_exist=True) as tag:
            native_materials={}
            for m in tag.tag.SelectField('Block:materials').Elements:
                ref=m.SelectField('render method').Path
                index=m.SelectField('imported material index').Data
                if ref is not None and 0<=index<len(native_emission):
                    native_materials.setdefault(str(ref.RelativePathWithExtension).replace('\\','/'),[]).append((index,native_emission[index]))
        verified=[]
        for m in bsp['materials'][:len(bsp['authoring']['materials'])]:
            s=m.get('lighting',{})
            if float(s.get('emissive power',0))<=0:continue
            destination=next(r['destination'] for r in plan['materials'] if r['source_shader']==m['source_shader'])
            expected={k:float(s[k]) for k in ('emissive power','emissive focus','attenuation falloff','attenuation cutoff')}
            expected['emissive color']=authoring.vector(s['emissive color'])
            if m.get('emissive_authoring'):
                spread=m['emissive_authoring']['target']['foundry_emissive_spread_radians']
                expected['emissive focus']=1-spread/math.pi
            matches=[]
            for index,native in native_materials.get(destination,[]):
                try:
                    for key,value in expected.items():close(native[key],value,destination+' '+key)
                except ValueError:continue
                matches.append(index)
            if not matches:
                raise ValueError('Source emissive material lacks matching native power/color/focus/attenuation: '+destination)
            verified.append(dict(source_material=m['slot'],source_shader=m['source_shader'],target=destination,
                native_material_info_indices=matches,expected=expected))
        rows.append(dict(bsp=bsp['destination'],definitions=len(light['definitions']),instances=len(light['instances']),emissive=verified))
    report['lighting_field_readback']=dict(status='VERIFIED_BEFORE_FAUX',bsps=rows)


def bitmaps(plan,paths,report,config):
    import bpy
    import numpy as np
    from io_scene_foundry.managed_blam.bitmap import BitmapTag
    from .native_bitmaps import REACH_CELLS
    rows=[]
    for image in report['bitmap_builds']:
        source=image['source_bitmap'].replace('\\','/')+'#0'
        spec=plan['bitmaps'][source]
        target=str(Path(image['destination']).with_suffix('.bitmap'))
        cube=bool(spec.get('source_layout'))
        with BitmapTag(path=target,tag_must_exist=True) as tag:
            if tag.block_bitmaps.Elements.Count!=1:raise ValueError('Native bitmap image count changed: '+target)
            element=tag.block_bitmaps.Elements[0]
            width=tag._select_int(element,'ShortInteger:width');height=tag._select_int(element,'ShortInteger:height')
            kind=tag._select_int(element,'CharEnum:type')
            offset=tag._select_int(element,'LongInteger:pixels offset');size=tag._select_int(element,'LongInteger:pixels size')
            if kind!=(2 if cube else 0) or size<=0 or offset<0:
                raise ValueError('Native bitmap type/pixel payload invalid: '+target)
            result=dict(source=source,target=target,type=kind,width=width,height=height,processed_bytes=size)
            if cube:
                expected=spec['dimensions']
                if [width,height,6]!=expected:raise ValueError('Native cube dimensions changed')
                # The retail MCC vertical-resource swizzle is not the loose
                # EK processed-data layout. Let Reach's own bitmap API decode
                # its imported payload, then inspect the native authoring atlas.
                from System import Array,Byte
                from System.Drawing import Rectangle
                from System.Drawing.Imaging import ImageLockMode,PixelFormat
                from System.Runtime.InteropServices import Marshal
                game=tag._GameBitmap()
                bitmap=game.GetBitmap()
                try:
                    if (bitmap.Width,bitmap.Height)!=(width*4,height*3):
                        raise ValueError('Native cube readback atlas dimensions changed: '+target)
                    locked=bitmap.LockBits(Rectangle(0,0,bitmap.Width,bitmap.Height),ImageLockMode.ReadOnly,PixelFormat.Format32bppArgb)
                    try:
                        if locked.Stride<=0:raise ValueError('Unsupported negative bitmap readback stride')
                        buffer=Array.CreateInstance(Byte,locked.Stride*bitmap.Height)
                        Marshal.Copy(locked.Scan0,buffer,0,len(buffer))
                        rgba=np.frombuffer(tag._dotnet_bytes_to_bytes(buffer),dtype=np.uint8).reshape(bitmap.Height,locked.Stride//4,4)[:,:bitmap.Width,[2,1,0,3]]
                        faces={name:rgba[y*height:(y+1)*height,x*width:(x+1)*width].copy()
                            for name,(x,y) in zip(('R','L','U','D','F','B'),REACH_CELLS)}
                    finally:bitmap.UnlockBits(locked)
                finally:
                    bitmap.Dispose();game.Dispose()
                source_path=Path(config['source_directory'])/spec['source_layout']['tiff']
                original=bpy.data.images.load(str(source_path),check_existing=False)
                original.colorspace_settings.name='Non-Color'
                pixels=np.empty(original.size[0]*original.size[1]*4,dtype=np.float32)
                original.pixels.foreach_get(pixels)
                atlas=pixels.reshape(original.size[1],original.size[0],4)[::-1]
                comparisons=[]
                for name,(x,y) in zip(('R','L','U','D','F','B'),spec['source_layout']['cells']):
                    reference=atlas[y*height:(y+1)*height,x*width:(x+1)*width,:3]
                    actual=faces[name][:,:,:3]/255
                    error=float(np.abs(reference-actual).mean())
                    comparisons.append(dict(face=name,mean_absolute_error=error))
                if any(r['mean_absolute_error']>.04 for r in comparisons):
                    data_image=bpy.data.images.load(str(paths.roots['data']/image['destination']),check_existing=False)
                    data_image.colorspace_settings.name='Non-Color'
                    data_pixels=np.empty(data_image.size[0]*data_image.size[1]*4,dtype=np.float32)
                    data_image.pixels.foreach_get(data_pixels)
                    artifact=Path(config['run_directory'])/('cube-diagnostic-'+Path(target).stem+'.npz')
                    np.savez_compressed(artifact,source_atlas=atlas.copy(),native_faces=np.stack([faces[n] for n in ('R','L','U','D','F','B')]),
                        target_atlas=data_pixels.reshape(data_image.size[1],data_image.size[0],4)[::-1])
                    result['diagnostic_pixels']=str(artifact)
                    bpy.data.images.remove(data_image)
                bpy.data.images.remove(original)
                result['face_readback']=comparisons
                rows.append(result);report['native_bitmap_readback']=rows
                if any(r['mean_absolute_error']>.04 for r in comparisons):
                    raise ValueError('Native cubemap face/orientation differs from source atlas: '+target+' '+str(comparisons))
                continue
            rows.append(result)
    report['native_bitmap_readback']=rows
