import sys,unittest,ast
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.surface_light_units import surface_attenuation_record,surface_native_updates,write_surface_attenuation
from port_environment.light_units import attenuation_record
class SurfaceUnits(unittest.TestCase):
 def source(self,flags='1'):
  return {'flags':flags,'attenuation falloff':'1','attenuation cutoff':'4','emissive power':'10','emissive color':'.4,.5,.6','emissive focus':'.2','emissive quality':'1','frustum blend':'0'}
 def test_enabled(self):
  r=surface_attenuation_record(self.source());self.assertEqual(list(r['REACH_AUTHORING_VALUES'].values()),[100,400]);self.assertEqual(list(r['EXPECTED_FAUX_EFFECTIVE_VALUES'].values()),[1,4])
 def test_disabled(self):
  r=surface_attenuation_record(self.source('0'));self.assertEqual(list(r['REACH_AUTHORING_VALUES'].values()),[2000,2100])
 def test_disabled_stored_distances_are_inactive(self):
  s=self.source('0');s['attenuation cutoff']='2';r=surface_attenuation_record(s);self.assertEqual(r['SOURCE_H3_SEMANTICS']['stored_distances']['attenuation cutoff'],2);self.assertEqual(r['EXPECTED_FAUX_EFFECTIVE_VALUES']['attenuation cutoff'],21)
 def test_source_and_other_semantics_immutable(self):
  s=self.source();s['self_illum_intensity']=7;before=deepcopy(s);surface_attenuation_record(s);self.assertEqual(s,before)
 def test_generic_unchanged(self):
  r=attenuation_record(dict(near_attenuation=[0,.4],far_attenuation=[1.992,4.83077]));self.assertEqual(r['REACH_AUTHORING_UNITS']['near_attenuation'],[0,40]);self.assertAlmostEqual(r['REACH_AUTHORING_UNITS']['far_attenuation'][1],483.077)
 def test_unsupported_fails(self):
  for key,value in [('flags','4'),('frustum blend','1'),('attenuation cutoff','0')]:
   s=self.source();s[key]=value
   with self.assertRaises(ValueError):surface_attenuation_record(s)
 def fixture(self):
  s=self.source();material=dict(slot=3,source_shader='source.shader',lighting=s)
  native={k:float(s[k]) for k in ('emissive power','emissive quality','emissive focus','attenuation falloff','attenuation cutoff')};native.update({'emissive color':[.4,.5,.6],'flags':0,'bounce ratio':1})
  return material,[dict(**{'render method':'target.shader','imported material index':0})],[native]
 def test_identity_native_mapping_and_idempotence(self):
  m,b,rows=self.fixture();r=surface_native_updates([m],{'source.shader':'target.shader'},b,rows);self.assertEqual(r[0]['native_row'],0)
  rows[0].update(r[0]['REACH_AUTHORING_VALUES']);r2=surface_native_updates([m],{'source.shader':'target.shader'},b,rows);self.assertEqual(r2[0]['REACH_AUTHORING_VALUES'],r[0]['REACH_AUTHORING_VALUES'])
 def test_unrelated_native_changes_rejected(self):
  m,b,rows=self.fixture();rows[0]['emissive power']=11
  with self.assertRaises(ValueError):surface_native_updates([m],{'source.shader':'target.shader'},b,rows)
 def test_normal_reach_rows_untouched(self):
  m,b,rows=self.fixture();before=deepcopy(rows);self.assertEqual(surface_native_updates([],{},b,rows),[]);self.assertEqual(rows,before)
 def test_writer_changes_only_two_fields(self):
  m,b,rows=self.fixture();r=surface_native_updates([m],{'source.shader':'target.shader'},b,rows);writes=[]
  class Field:
   def __setattr__(self,k,v):writes.append((k,v))
  class Element:
   def SelectField(self,k):writes.append(k);return Field()
  class Block:Elements=[Element()]
  class Tag:
   def SelectField(self,k):self.name=k;return Block()
  write_surface_attenuation(Tag(),r);self.assertEqual(writes,['attenuation falloff',('Data',100),'attenuation cutoff',('Data',400)])

 def test_real_face_adapter_round_trip_preserves_nonrange_values(self):
  from types import ModuleType,SimpleNamespace
  from unittest.mock import patch
  from port_environment import native_scene
  utils=SimpleNamespace(srgb_to_linear=lambda x:x**2.2)
  package=ModuleType('io_scene_foundry');package.utils=utils
  constants=ModuleType('io_scene_foundry.constants');constants.WU_SCALAR=3.048
  for flag,expected in [('1',(100,400)),('0',(2000,2100))]:
   captured=[];source=self.source(flag);before=deepcopy(source)
   with patch.dict(sys.modules,{'io_scene_foundry':package,'io_scene_foundry.constants':constants}), patch.object(native_scene,'face_property',side_effect=lambda mesh,kind,values,selected:captured.append(values)):
    native_scene.render_properties(SimpleNamespace(data=object()),{'triangles':[{'material':0}]},[],[{'lighting':source}],[])
   props=captured[0]
   self.assertAlmostEqual(props['material_lighting_attenuation_falloff']*100*3.048,expected[0])
   self.assertAlmostEqual(props['material_lighting_attenuation_cutoff']*100*3.048,expected[1])
   self.assertEqual(props['material_lighting_emissive_power'],10)
   self.assertEqual(props['material_lighting_emissive_color'],[x**2.2 for x in [.4,.5,.6]])
   self.assertAlmostEqual(props['material_lighting_emissive_focus'],__import__('math').pi*.8)
   self.assertEqual(source,before)

if __name__=='__main__':unittest.main()
