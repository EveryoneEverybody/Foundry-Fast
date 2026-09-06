"""Actual Blender image loading and serial bitmap code with mocked tag fields."""
import importlib
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1] / 'blender/addons/io_scene_foundry'
NAME = 'parallel_bitmap_smoke'
package = ModuleType(NAME); package.__path__ = [str(ROOT)]; sys.modules[NAME] = package
for name in ('tools', 'managed_blam'):
    module = ModuleType(NAME+'.'+name); module.__path__ = [str(ROOT/name)]
    sys.modules[module.__name__] = module
utils = ModuleType(NAME+'.utils'); sys.modules[utils.__name__] = utils
output = ModuleType(NAME+'.foundry_output'); sys.modules[output.__name__] = output
preferences = ModuleType(NAME+'.preferences'); sys.modules[preferences.__name__] = preferences
backend = ModuleType(NAME+'.tools.importer'); sys.modules[backend.__name__] = backend
shader_module = ModuleType(NAME+'.managed_blam.shader'); sys.modules[shader_module.__name__] = shader_module

class ImageProps(bpy.types.PropertyGroup):
    filepath: bpy.props.StringProperty()
    shader_type: bpy.props.StringProperty()
class TestPreferences(bpy.types.PropertyGroup):
    bitmap_color_space_conversion: bpy.props.BoolProperty(default=True)
preferences.FoundryPreferences = TestPreferences
bpy.utils.register_class(ImageProps)
bpy.types.Image.nwo = bpy.props.PointerProperty(type=ImageProps)

class Box:
    def __init__(self, title): self.title=title
    def prop(self, prefs, name): drawn.append((self.title,name))
drawn=[]
preferences._settings_box=lambda layout,title:Box(title)
logs=[]
utils.print_warning=lambda s:logs.append(s)
utils.print_error=lambda s:logs.append(s)
output.print_detail=lambda s:logs.append(s)
output._raise_if_cancel_requested=lambda:None

storage=tempfile.TemporaryDirectory(prefix='foundry bitmap test with spaces ')
tags=Path(storage.name)/'tags';data=Path(storage.name)/'data';tags.mkdir();data.mkdir()
utils.get_tags_path=lambda:str(tags)
utils.get_data_path=lambda:str(data)
def relative(value):
    p=Path(value)
    if p.is_absolute():
        for root in (tags,data):
            try:return p.relative_to(root).as_posix()
            except ValueError:pass
    return p.as_posix()
utils.relative_path=relative
utils.run_tool=lambda *a,**k:None
main_thread=threading.get_ident()
reads=[];live_tags=set();fixtures={}

class Field:
    def __init__(self,value=None,items=None):
        self.Data=value;self.Value=value;self.Items=items or []
    def GetData(self):
        assert threading.get_ident()==main_thread
        return self.Data
class Elements(list):
    @property
    def Count(self):return len(self)
class Block:
    def __init__(self,values):self.Elements=Elements(values)
class Element:
    ElementIndex=0
    def __init__(self,fixture,index=0):self.fixture=fixture;self.ElementIndex=index
    def SelectField(self,name):
        field=name.partition(':')[-1]
        spec=self.fixture
        values={'width':spec['width'],'height':spec['height'],'format':spec['format'],
                'type':spec.get('type',0),'curve':spec.get('curve',0),'pixels offset':0,
                'pixels size':len(spec['pixels'])}
        return Field(values[field])
class FakeTag:
    def __init__(self,fixture):self.fixture=fixture
    def SelectField(self,name):
        assert threading.get_ident()==main_thread
        spec=self.fixture
        if name=='Block:bitmaps':return Block([Element(spec,i) for i in range(spec.get('frames',1))])
        if name=='LongEnum:Usage':return Field(spec.get('usage',0),[SimpleNamespace(DisplayName='normal' if i==2 else 'diffuse') for i in range(40)])
        if name=='CharEnum:curve mode':return Field(0)
        if name=='Block:usage override':return Block([])
        if name=='Block:bitmaps[0]/CharEnum:curve':return Field(spec.get('curve',0))
        if name=='Data:processed pixel data':return Field(spec['pixels'])
        raise KeyError(name)
class Tag:
    def __init__(self,path='',**kwargs):
        assert threading.get_ident()==main_thread
        rel=relative(path);reads.append((rel,threading.get_ident()))
        self.tag_path=SimpleNamespace(RelativePathWithExtension=rel,RelativePath=str(Path(rel).with_suffix('')),
                                      ShortName=Path(rel).stem,Filename=str(tags/rel))
        self.tags_dir=str(tags);self.data_dir=str(data);self.corinth=False
        self.tag=FakeTag(fixtures[rel]);self._read_fields();live_tags.add(self)
    def __enter__(self):return self
    def __exit__(self,*args):live_tags.remove(self)
sys.modules[NAME+'.managed_blam'].Tag=Tag
bitmaps=importlib.import_module(NAME+'.managed_blam.bitmap')
shader_module.bitmap_to_image=bitmaps.bitmap_to_image

class Param:
    def __init__(self,path):self.path=path
    def SelectField(self,name):return SimpleNamespace(Path=SimpleNamespace(Filename=str(tags/self.path)))

created=[]
class ShaderTag:
    corinth=False
    def __init__(self,paths):self.paths=paths;self.block_parameters=Block([Param(p) for p in paths])
    def to_nodes(self,material,always_extract_bitmaps=False,generated_uvs=False):
        for path in self.paths:
            assert threading.get_ident()==main_thread
            info=shader_module.bitmap_to_image(str(tags/path),always_extract_bitmaps)
            if info.image:
                node=material.node_tree.nodes.new('ShaderNodeTexImage');node.image=info.image
                if info.for_normal:material.node_tree.nodes.new('ShaderNodeNormalMap')
                created.append(info)
shader_module.ShaderTag=ShaderTag

paths=['textures/color.bitmap','textures/normal.bitmap','textures/reflection.bitmap','textures/other.bitmap']
for index,path in enumerate(paths):
    fmt=38 if index==1 else 16
    block=bytes((231,47,11,89,123,4,200,91,0,248,224,7,1,35,69,103))
    spec={'width':128,'height':128,'format':fmt,'type':2 if index==2 else 0,
          'curve':3 if index==1 else 0,'usage':2 if index==1 else 0,
          'pixels':block*(32*32*(6 if index==2 else 1))}
    fixtures[path]=spec;(tags/path).parent.mkdir(parents=True,exist_ok=True);(tags/path).write_bytes(b'source tag read only '+bytes([index]))
original_tags={p:(tags/p).read_bytes() for p in paths}

def setup(context, importer, starting, objects, build, forced=False, emissive=None):
    if build:
        material=bpy.data.materials.new('pipeline material');material.use_nodes=True
        ShaderTag(importer.paths).to_nodes(material,forced)
        importer.material=material
backend.setup_materials=setup

parallel=importlib.import_module(NAME+'.parallel_bitmaps')
parallel.prepare();bpy.utils.register_class(TestPreferences)
bpy.types.Scene.bitmap_test_prefs=bpy.props.PointerProperty(type=TestPreferences)
utils.get_prefs=lambda:bpy.context.scene.bitmap_test_prefs
prefs=utils.get_prefs()
parallel.MIN_PIXELS=1
cache=importlib.import_module(NAME+'.perf_bitmap_cache')
cache.register();parallel.register()
pools=[];sessions=[]
RealPool=parallel.Pool;RealSession=parallel.Session
class TrackedPool(RealPool):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);pools.append(self)
class TrackedSession(RealSession):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);sessions.append(self)
parallel.Pool=TrackedPool;parallel.Session=TrackedSession
original_cpu_count=parallel.os.cpu_count
parallel.os.cpu_count=lambda:4

def reset():
    for p in data.rglob('*'):
        if p.is_file():p.unlink()
    bitmaps.path_cache.clear();bitmaps.used_plate_paths.clear();created.clear()
    for image in list(bpy.data.images):bpy.data.images.remove(image)

def run(count='0',forced=False,source_paths=None,corinth=False):
    prefs.parallel_bitmap_workers=count
    importer=SimpleNamespace(corinth=corinth,paths=source_paths or paths)
    backend.setup_materials(bpy.context,importer,[],[],True,forced)
    return importer

try:
    assert prefs.parallel_bitmap_workers=='0'
    preferences._settings_box(None,'Import & Bitmaps')
    assert drawn==[('Import & Bitmaps','parallel_bitmap_workers')]
    # The off path is unchanged and allocates no workers.
    run('0')
    serial={str(p.relative_to(data)):p.read_bytes() for p in data.rglob('*.tiff')}
    assert len(serial)==5 and not pools and not live_tags,logs
    reset()
    importer=run('2',source_paths=paths+[paths[0]])
    parallel_outputs={str(p.relative_to(data)):p.read_bytes() for p in data.rglob('*.tiff')}
    assert parallel_outputs==serial
    assert len(pools)==1 and pools[0].stats['peak_running_jobs']==2
    assert sessions[-1].stats['prepared_images_used']==4
    assert created[0].image==created[-1].image
    assert created[1].image.colorspace_settings.name=='Non-Color'
    assert created[0].image.colorspace_settings.name=='sRGB'
    assert all(info.image.alpha_mode=='CHANNEL_PACKED' for info in created if not info.for_normal)
    assert all(p.closed and not p.folder.exists() for p in pools)
    assert all(slot['process'].poll() is not None for p in pools for slot in p.slots)
    assert not live_tags and not parallel._sessions
    # Save/reopen with the worker spool already removed.
    image_names=[info.image.name for info in created]
    blend=Path(storage.name)/'result.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    prefs=utils.get_prefs()
    assert all(bpy.data.images.get(name) is not None for name in image_names)
    assert bpy.data.images[image_names[1]].colorspace_settings.name=='Non-Color'
    before=len(pools);run('2');assert len(pools)==before
    # Forced extraction and Corinth never start the worker experiment.
    reset();run('2',forced=True);assert len(pools)==before
    reset();run('2',corinth=True);assert len(pools)==before
    # Worker failure retries the original extraction and produces identical files.
    reset()
    class FailingPool(TrackedPool):
        def take(self,*args,**kwargs):raise RuntimeError('synthetic worker failure')
    parallel.Pool=FailingPool
    run('2')
    assert {str(p.relative_to(data)):p.read_bytes() for p in data.rglob('*.tiff')}==serial
    assert sessions[-1].stats['serial_retries']==4
    assert not live_tags and not parallel._sessions
    # An invalid preflight is not allowed to break the normal material path.
    reset();parallel.Pool=TrackedPool
    old_capture=TrackedSession.capture
    TrackedSession.capture=lambda *args:(_ for _ in ()).throw(ValueError('synthetic capture failure'))
    try:run('2')
    finally:TrackedSession.capture=old_capture
    assert {str(p.relative_to(data)):p.read_bytes() for p in data.rglob('*.tiff')}==serial
    assert {p:(tags/p).read_bytes() for p in paths}==original_tags
    assert all(ident==main_thread for _,ident in reads)
finally:
    parallel.os.cpu_count=original_cpu_count
    parallel.unregister();cache.unregister()
    storage.cleanup()
print('Parallel bitmap Blender checks passed: real serial decoder and image loader, worker equivalence, main-thread tag access, colors and normals, reuse, warm/forced/Corinth bypass, serial retries, source preservation and persistence')
