"""Small incremental population fixtures; no campaign assets or native runtime."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment import population


def fixture():
    families = {f: dict(palette=[], placements=[]) for f in population.SUPPORTED}
    source = dict(source_scenario='levels/source.scenario', source_sha256='revision1',
                  object_names=[dict(source_index=7, name='door'), dict(source_index=9, name='button')],
                  device_groups=[dict(source_index=8, name='shared', semantic={'initial': 0})],
                  families=deepcopy(families))
    target = dict(object_names=[dict(name='foreign', uses=[dict(family='weapons', index=0)])],
                  device_groups=[dict(name='foreign', semantic={'initial': 1})], families=deepcopy(families),
                  protected={'bsps': ['b'], 'zone_sets': ['a', 'b'], 'triggers': [1]})
    target['families']['machines']['palette'] = [dict(target_tag='foreign.device_machine')]
    target['families']['machines']['placements'] = [dict(target_tag='foreign.device_machine', unique_id='999',
                                                         fingerprint='foreign', semantic='foreign')]
    def add(f, index, name, uid, parent=-1):
        source['families'][f]['palette'].append(dict(source_index=47, target_tag=f+'.tag'))
        source['families'][f]['placements'].append(dict(family=f, source_index=index,
            source_palette_index=47, source_object_name_index=name, unique_id=uid,
            device_groups={'power group': 8, 'position group': 8}, parent={'source_name_index': parent},
            native_status='READY', semantic=uid))
    add('machines', 3, 7, '101')
    add('controls', 4, 9, '102', 7)
    return source, target


def simulate(target, result, source):
    target = deepcopy(target)
    for m in result['mutations']:
        if m['table'] == 'palette':
            target['families'][m['family']]['palette'].append(dict(target_tag=m['target_tag']))
        elif m['table'] == 'object_names':
            target['object_names'].append(dict(name=m['name'], uses=[]))
        elif m['table'] == 'device_groups':
            target['device_groups'].append(deepcopy(source['device_groups'][0]))
    provenance = {}
    for row in result['placements']:
        native = dict(target_tag=row['family']+'.tag', unique_id=row['unique_id'],
                      semantic=row['semantic'], fingerprint=row['unique_id'])
        block = target['families'][row['family']]['placements']
        if row['action'] == 'APPEND':
            block.append(native)
        target['object_names'][row['target_object_name_index']]['uses'] = [dict(family=row['family'], index=row['target_index'])]
        provenance[row['logical_id']] = dict(family=row['family'], target_index=row['target_index'],
                                             target_fingerprint=row['unique_id'])
    return target, provenance


class Population(unittest.TestCase):
    def test_native_noop_does_not_touch_or_save_tag(self):
        from port_environment import native_population
        tag=Mock()
        self.assertEqual(native_population.apply(tag,dict(mode=population.MODE,semantic_mutation_count=0),{}),
                         dict(saved=False,semantic_mutations=0))
        self.assertEqual(tag.mock_calls,[])

    def test_native_population_cannot_clear_protected_tables(self):
        from port_environment import native_population
        class Elements(list):
            @property
            def Count(self):return len(self)
        class Block:
            def __init__(self):self.Elements=Elements()
            def AddElement(self):
                e=Mock();self.Elements.append(e);return e
            def RemoveAllElements(self):raise AssertionError('Population attempted full replacement')
        palette=Block();palette.Elements.append(Mock())
        scenario=Mock()
        def select(name):
            if name!='scenery palette':raise AssertionError('Population touched protected table: '+name)
            return palette
        scenario.tag.SelectField.side_effect=select
        result=dict(mode=population.MODE,semantic_mutation_count=1,placements=[],designer_zone_additions=[],
                    mutations=[dict(table='palette',family='scenery',index=1,target_tag='new.scenery')])
        native_population.apply(scenario,result,{})
        self.assertEqual(len(palette.Elements),2)
        scenario.tag.Save.assert_called_once()

    def test_closure_keeps_missing_source_names_and_semantic_roles(self):
        from port_environment import asset_closure
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('a.crate','a.model','a.render_model','a.shader'):(root/name).write_bytes(b'source')
            objects=[dict(source_tag='a.crate',object_ir=dict(model='a.model',render_model='a.render_model',
                materials=['a.shader'],dependency_provenance=[dict(source_tag='unknown.effect',source_field='/attachment')]))]
            shaders={'a.shader':dict(parameters=[dict(name='base_map',bitmap='missing color#0')])}
            graph=asset_closure.graph(objects,shaders,{},root)
            self.assertFalse(graph['nodes']['missing color.bitmap']['source_exists'])
            self.assertEqual(graph['nodes']['unknown.effect']['disposition'],'BLOCKING_UNKNOWN')
            self.assertIn('shader.bitmap:base_map',{r['semantic_role'] for r in graph['edges'].values()})
            self.assertEqual(len(graph['roots']),1)

    def test_specialized_census_streams_counts_without_resource_payloads(self):
        from port_environment import scenario_census
        with tempfile.TemporaryDirectory() as directory:
            xml=Path(directory)/'source.xml'
            xml.write_text('<tag>\n    <block name="decorators" value=",1">\n'
                '        <block name="placements" value=",60946">\n'
                '        <field name="set" value="grass,dctr" type="tag reference"/>\n'
                '    </block>\n</tag>\n')
            result=scenario_census.specialized(xml,dict(source_section_counts={'decorators':1},object_dependencies={}))
            self.assertEqual(result['systems'][0]['nested_block_counts'],{'placements':60946})
            self.assertEqual(result['systems'][0]['source_references'],['grass,dctr'])

    def test_selective_root_receipt_reuse(self):
        from port_environment.object_receipts import root_identity, reusable_root
        identity = root_identity('a.crate', 'crate', {'a.crate':'sha'}, 'crate-rule', 'closure', 'native.crate')
        receipt = dict(status='NATIVE_AUTHORED_READBACK_VERIFIED', identity=identity,
                       native_readback={'status':'VERIFIED'}, output_files={'native.crate':'output'})
        self.assertTrue(reusable_root(receipt, identity, {'native.crate':'output','other.scenery':'changed'}))
        for key in ('rule_fingerprint','closure_fingerprint','source_revision_sha256'):
            self.assertFalse(reusable_root(receipt, dict(identity, **{key:'changed'}), {'native.crate':'output'}))
        self.assertFalse(reusable_root(receipt, identity, {'native.crate':'user edit'}))

    def test_duplicate_source_uid_cannot_claim_new_row(self):
        source, target = fixture()
        group=source['families']['machines']
        group['placements'].append(dict(group['placements'][0],source_index=4,source_object_name_index=-1))
        result=population.reconcile(source,target)
        self.assertEqual(len(result['deferred']),1)
        self.assertIn('Multiple source placements',result['deferred'][0]['reason'])

    def test_sparse_indices_groups_parent_and_foreign_preservation(self):
        source, target = fixture()
        before = deepcopy(target)
        result = population.reconcile(source, target)
        machine, control = result['placements']
        self.assertEqual(result['palette_maps']['machines'], {47: 1})
        self.assertEqual(machine['target_index'], 1)
        self.assertEqual(result['object_name_map'], {7: 1, 9: 2})
        self.assertEqual(control['target_parent_name_index'], 1)
        self.assertEqual(machine['target_device_groups'], control['target_device_groups'])
        self.assertEqual(result['device_group_map'], {8: 1})
        self.assertEqual(target, before)
        self.assertTrue(all(m['table'] in {'palette', 'placements', 'object_names', 'device_groups'} for m in result['mutations']))

    def test_second_pass_noop_with_provenance_and_bootstrap(self):
        source, target = fixture()
        first = population.reconcile(source, target)
        installed, provenance = simulate(target, first, source)
        for prov in (provenance, None):
            second = population.reconcile(source, installed, provenance=prov)
            self.assertEqual(second['semantic_mutation_count'], 0)
            self.assertEqual([r['action'] for r in second['placements']], ['UNCHANGED', 'UNCHANGED'])
            self.assertFalse(second['deferred'])

    def test_shared_root_palette_is_deduplicated(self):
        source, target = fixture()
        group = source['families']['machines']
        group['palette'].append(dict(source_index=99, target_tag='machines.tag'))
        group['placements'].append(dict(group['placements'][0], source_index=8, source_palette_index=99,
                                         source_object_name_index=-1, unique_id='103', semantic='103'))
        result = population.reconcile(source, target)
        self.assertEqual(result['palette_maps']['machines'], {47: 1, 99: 1})
        self.assertEqual(len([m for m in result['mutations'] if m['table']=='palette' and m['family']=='machines']), 1)

    def test_ambiguous_identity_preserves_unowned(self):
        source, target = fixture()
        target['families']['machines']['placements'] += [dict(target_tag='machines.tag', unique_id='101')]*2
        result = population.reconcile(source, target)
        self.assertFalse(result['mutations'])
        self.assertIn('Ambiguous', result['deferred'][0]['reason'])
        self.assertEqual(len(result['deferred']), 2)

    def test_changed_unowned_or_owned_placement_is_preserved(self):
        source, target = fixture()
        first = population.reconcile(source, target)
        installed, provenance = simulate(target, first, source)
        installed['families']['machines']['placements'][1].update(semantic='user edit', fingerprint='edited')
        for prov in (None, provenance):
            result = population.reconcile(source, installed, provenance=prov)
            self.assertFalse(result['mutations'])
            self.assertEqual(len(result['deferred']), 2)

    def test_conflicting_group_does_not_stop_independent_root(self):
        source, target = fixture()
        target['device_groups'].append(dict(name='shared', semantic={'initial': 1}))
        control = source['families']['controls']['placements'][0]
        control.update(parent={'source_name_index': -1}, device_groups={})
        result = population.reconcile(source, target)
        self.assertEqual([r['family'] for r in result['placements']], ['controls'])
        self.assertIn('group semantics differ', result['deferred'][0]['reason'])

    def test_unrelated_name_owner_is_not_overwritten_or_renamed(self):
        source, target = fixture()
        target['object_names'][0]['name'] = 'door'
        result = population.reconcile(source, target)
        self.assertFalse(result['mutations'])
        self.assertIn('belongs to another placement', result['deferred'][0]['reason'])

    def test_same_logical_identity_can_update_source_revision(self):
        source, target = fixture()
        installed, provenance = simulate(target, population.reconcile(source, target), source)
        source['source_sha256'] = 'revision2'
        source['families']['machines']['placements'][0]['semantic'] = 'new transform'
        result = population.reconcile(source, installed, provenance=provenance)
        self.assertEqual([r['action'] for r in result['placements']], ['UPDATE', 'UNCHANGED'])
        self.assertEqual(result['semantic_mutation_count'], 1)


if __name__ == '__main__':
    unittest.main()
