"""No engine jobs: unit conversion, native adapter, stage/restore/failure guards."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.light_units import attenuation_record, reach_attenuation_units
from port_environment import native_scene
spec=importlib.util.spec_from_file_location('manual_runner',ROOT/'tools/manual_bake/runner.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
sspec=importlib.util.spec_from_file_location('manual_solver',ROOT/'tools/manual_bake/solver.py')
solver=importlib.util.module_from_spec(sspec);sspec.loader.exec_module(solver)


class Units(unittest.TestCase):
    def test_world_authoring_and_load_units_are_distinct_and_plan_immutable(self):
        source=dict(near_attenuation=[0,.4],far_attenuation=[1.992,4.83077],intensity=3)
        saved=deepcopy(source);record=attenuation_record(source)
        self.assertEqual(record['REACH_AUTHORING_UNITS']['near_attenuation'],[0,40])
        for actual,expected in zip(record['REACH_AUTHORING_UNITS']['far_attenuation'],[199.2,483.077]):self.assertAlmostEqual(actual,expected)
        for name in ('near_attenuation','far_attenuation'):
            for x,y in zip(record['REACH_AUTHORING_UNITS'][name],source[name]):self.assertAlmostEqual(x*.01,y)
        self.assertEqual(record['EXPECTED_FAUX_WORLD_UNITS'],record['SOURCE_WORLD_UNITS'])
        self.assertEqual(source,saved)

    def test_finite_float32_guard(self):
        for value in (float('nan'),float('inf'),1e40):
            with self.assertRaises(ValueError):reach_attenuation_units(value)

    def test_real_translator_adapter_only_converts_distances(self):
        d=dict(source_index=0,source_fields={'shape':'rectangle'},type=1,shape=1,color=[.7,.6,.5],intensity=3,
               hotspot_size=23.3,hotspot_cutoff=50.8,hotspot_falloff=1,aspect=2.76,flags=2,near_attenuation=[0,.4],far_attenuation=[1.992,4.83077])
        ip=dict(source_index=104,definition_index=0,origin=[1,2,3],forward=[1,0,0],up=[0,0,1])
        plan=dict(bsps=[dict(region='slice',source_tag='source',destination='levels/test/slice.scenario_structure_bsp')],lighting_by_bsp=[dict(definitions=[d],instances=[ip])])
        saved=deepcopy(plan);calls=[]
        class Tag:
            def __init__(self,**kw):self.tag=SimpleNamespace(SelectField=lambda x:SimpleNamespace(Elements=SimpleNamespace(Count=5)),Save=lambda:None)
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def update_reach_attenuation(self,definitions):calls.extend(vars(x) for x in definitions)
        mod=ModuleType('io_scene_foundry.managed_blam.scenario_structure_lighting_info');mod.ScenarioStructureLightingInfoTag=Tag
        with patch.dict(sys.modules,{'io_scene_foundry.managed_blam.scenario_structure_lighting_info':mod}):native_scene.write_static_lights(plan,{},attenuation_only=True)
        self.assertEqual(plan,saved);self.assertEqual(calls[0]['intensity'],3);self.assertEqual(calls[0]['shape'],0)
        self.assertAlmostEqual(calls[0]['far_attenuation_end'],483.077);self.assertEqual(calls[0]['near_attenuation_end'],40)
        for key in ('color','hotspot_size','hotspot_cutoff','aspect'):self.assertEqual(calls[0][key],d[key])


class Farm(unittest.TestCase):
    def test_prepare_only_never_dispatches_faux(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);kit=root/'kit';(kit/'bin').mkdir(parents=True);(kit/'tags/globals').mkdir(parents=True)
            for rel in ('bin/ManagedBlam.dll','project.xml','tags/globals/lightmapper_globals.lightmapper_globals'):(kit/rel).write_text('fixture')
            stages=runner.pipeline('s','b','low',1,1)
            (kit/'tool_fast.exe').write_text('\n'.join(cmd[0] for g in stages for cmd in g))
            (root/'plan.json').write_text('{}')
            config=dict(HrekRoot=str(kit),Scenario='levels/test/test',RunRoot=str(root/'runs'),Blender='unused',Mode='PrepareOnly',Plan=str(root/'plan.json'),OutputNamespace='levels/proof',Bsp=['0'])
            def native(c,out,action,**kw):
                if action=='inspect':return dict(bsps=['levels/test/bsp.scenario_structure_bsp'],output_dependencies=[],scenario_bsp_rows=[{'structure lighting_info':'levels/test/bsp.scenario_structure_lighting_info'}],qualities=[dict(name='low',flags=3)])
                self.assertEqual(action,'prepare');self.assertEqual(kw['indices'],[0])
                return dict(status='PASS',preparation=[])
            with patch.object(runner,'native',side_effect=native),patch.object(runner,'execute_group',side_effect=AssertionError('Faux forbidden')):
                self.assertEqual(runner.run(config),0)
            output=next((root/'runs').iterdir());result=json.loads((output/'result.json').read_text())
            self.assertFalse(result['faux_started']);self.assertEqual(result['stages'],[])
            self.assertFalse((kit/'faux').exists())
    def test_worker_partitions_and_merges(self):
        groups=runner.pipeline('levels/test/test','bsp0','low',12,456)
        self.assertEqual(len(groups),13)
        for phase in ('dillum','pcast','radest_extillum','fgather'):
            clients=next(g for g in groups if g[0][0]=='faux_farm_'+phase)
            self.assertEqual([x[-2:] for x in clients],[[str(i),'12'] for i in range(12)])
            merge=next(g for g in groups if g[0][0]=='faux_farm_'+phase+'_merge')
            self.assertEqual(merge[0][-1],'12')
        self.assertEqual(groups[1][0][3],'')

    def test_direct_only_omits_disabled_work(self):
        groups=runner.pipeline('s','b','direct_only',2,3)
        self.assertEqual(len(groups),7)
        self.assertFalse(any(any(x in cmd[0] for x in ('pcast','radest','fgather')) for g in groups for cmd in g))

    def test_draft_has_final_gather_without_photon_mapping(self):
        stages=[g[0][0] for g in runner.pipeline('s','b','draft',2,3)]
        self.assertNotIn('faux_farm_pcast',stages)
        self.assertNotIn('faux_farm_pcast_merge',stages)
        self.assertIn('faux_farm_radest_extillum',stages)
        self.assertIn('faux_farm_fgather_merge',stages)
        self.assertEqual(len(stages),11)

    def test_selections_are_scenario_indices_not_source_indices(self):
        paths=['levels/test/slice_0000.scenario_structure_bsp','levels/test/slice_0001.scenario_structure_bsp']
        self.assertEqual(runner.select_bsps(['0001','0000'],paths),([1,0],False))
        self.assertEqual(runner.select_bsps('all',paths),([0,1],True))
        self.assertEqual(runner.select_bsps('slice_0000',paths),([0],False))
        for invalid in ('2','all,0','0,0','missing'):
            with self.assertRaises(ValueError):runner.select_bsps(invalid,paths)

    def test_log_failure_even_on_zero_exit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'log';p.write_text('SUCCEEDED\nLIGHTMAPPER FAILED\n### ASSERTION FAILED\nwarning: test\n')
            r=runner.scan_log(p);self.assertEqual(r['fatal_lines'],[2,3]);self.assertTrue(r['success_marker'])

    def test_failed_client_stops_other_owned_clients_without_waiting_for_them(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'logs').mkdir();status=dict(start_epoch=time.time(),workers=2,stages=[])
            start=time.monotonic()
            with self.assertRaisesRegex(RuntimeError,'exit=7'):
                runner.execute_group([['-c','import sys;sys.exit(7)'],['-c','import time;time.sleep(60)']],Path(sys.executable),p,p,0,status,1)
            self.assertLess(time.monotonic()-start,15)
            self.assertTrue(all(r['exit_code'] is not None for r in status['stages']))
            self.assertEqual(status['stages'][0]['exit_code'],7)

    def test_no_installed_mutation_without_explicit_policy(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'kit/bin').mkdir(parents=True);(p/'kit/bin/ManagedBlam.dll').write_bytes(b'fixture')
            cfg=dict(HrekRoot=str(p/'kit'),Scenario='levels/test/test',RunRoot=str(p/'runs'),Mode='BakeOnly',Quality='low',Workers=1,Blender='unused')
            with patch.object(runner,'native',side_effect=AssertionError('must not reach native')):
                with self.assertRaisesRegex(ValueError,'GuardedInPlace'):runner.run(cfg)


class Restore(unittest.TestCase):
    def fixture(self, root):
        kit=root/'kit';kit.mkdir();target=kit/'tags/levels/test';target.mkdir(parents=True);run=root/'run';run.mkdir()
        (target/'existing').write_bytes(b'baseline');before=runner.inventory(target);runner.backup(target,run,before)
        (target/'existing').write_bytes(b'candidate');(target/'new').write_bytes(b'new-output');after=runner.inventory(target)
        runner.write(run/'config.json',dict(HrekRoot=str(kit),ProtectedRoot=str(target)))
        runner.write(run/'hashes-before.json',before);runner.write(run/'hashes-after.json',after)
        return kit,target,run,before,after

    def test_exact_restore_and_completed_evidence_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            kit,target,run,before,after=self.fixture(Path(d));evidence=runner.inventory(run)
            runner.restore(run)
            self.assertEqual(runner.inventory(target),before);self.assertEqual(runner.inventory(run),evidence)

    def test_concurrent_edits_new_files_and_corrupt_backup_refuse_before_writes(self):
        for change in ('edit','new','backup'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                kit,target,run,_,_=self.fixture(Path(d))
                p={'edit':target/'existing','new':target/'unrelated','backup':run/'backups/existing'}[change];p.write_bytes(b'concurrent')
                current=runner.inventory(target)
                with self.assertRaises(ValueError):runner.restore(run)
                self.assertEqual(runner.inventory(target),current)

    def test_lock_and_missing_after_never_guess_resume(self):
        with tempfile.TemporaryDirectory() as d:
            kit,target,run,_,after=self.fixture(Path(d));(run/'hashes-after.json').unlink()
            with self.assertRaises(FileNotFoundError):runner.restore(run)
            self.assertEqual(runner.inventory(target),after)
            lock=kit/'.foundry-manual-bake.lock';lock.write_text('interrupted')
            with self.assertRaises(ValueError):runner.restore(run)
            self.assertEqual(lock.read_text(),'interrupted')

    def test_path_traversal_refused(self):
        for p in ('../x','/absolute','C:/tags','a//b','a/../b'):
            with self.assertRaises(ValueError):runner.logical(p)


class Solver(unittest.TestCase):
    def test_effective_range_guard_rejects_old_hundredth_scale(self):
        import math,struct
        d={'type':1,'shape':0,'flags':10,'color':[.7,.6,.5],'intensity':3,'aspect':2.76,'hotspot size':23.3,'hotspot cutoff size':50.8}
        ip={'origin':[1,2,3],'forward':[1,0,0],'up':[0,0,1],'bungie light type':0}
        probe=dict(definition_input=d,instance=ip,expected_world={'near_attenuation':[0,.4],'far_attenuation':[1.992,4.83077]})
        instance=struct.pack('<13fIIfI',1,1,0,0,0,1,0,0,0,1,1,2,3,23,0,1,0)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'main.blob'
            for scale in (1,.01):
                definition=struct.pack('<4i7fi5f',1,0,0,6,*[x**2.2 for x in d['color']],3,math.radians(23.3)/2,math.radians(50.8)/2,1,0,0,0,1.992*scale,4.83077*scale,2.76)
                path.write_bytes(b'\0'*256+definition+b'\0'*128+instance)
                if scale==1:self.assertEqual(solver.verify(path,probe)['status'],'MATCHING_SOLVER_PARAMETERS_VERIFIED')
                else:
                    with self.assertRaisesRegex(ValueError,'range mismatch'):solver.verify(path,probe)


if __name__=='__main__':unittest.main()
