"""A diagnostic fixture must not silently alter campaign data or remove edits."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import prepare_h3_player_interaction as fixture


class PlayerFixtureGuards(unittest.TestCase):
    def documents(self):
        before = ET.fromstring('''<tag group="scenario" id="main">
<field name="player starting locations" value="1" type="block"/>
<element index="0"><field name="position" value="0,0,0"/><field name="facing" value="0"/><field name="pitch" value="0"/><field name="flags" value="original"/></element>
<field name="cutscene flags" value="0" type="block"/>
<field name="trigger volumes" value="1" type="block"/>
<element index="0"><field name="name" value="kill_cleanup"/><field name="kill trigger volume" value="NONE"/></element>
<field name="object names" value="0" type="block"/>
</tag>''')
        after = deepcopy(before)
        after.set('id', 'fixture')
        fixture.fixtures.block(after, 'player starting locations')[0][0].set('value', '1,2,3')
        marker = next(e for e in after if e.get('name') == 'cutscene flags')
        marker.set('value', '1')
        after.insert(list(after).index(marker) + 1, ET.fromstring('''<element index="0"><field name="name" value="diag"/><field name="position" value="1,2,3"/><field name="facing" value="0,0"/></element>'''))
        spec = dict(initial_flag='diag', flags=[dict(name='diag', position=[1, 2, 3], facing_degrees=0)])
        return before, after, spec

    def test_expected_diff_and_poses_pass(self):
        before, after, spec = self.documents()
        self.assertEqual(len(fixture.verify_difference(before, after)), 2)
        fixture.verify_poses(before, after, spec)

    def test_unrelated_native_load_defaults_are_rejected(self):
        before, after, _ = self.documents()
        fixture.fixtures.block(after, 'trigger volumes')[0][1].set('value', '0')
        with self.assertRaisesRegex(ValueError, 'Unexpected scenario change: trigger volumes'):
            fixture.verify_difference(before, after)
        after = deepcopy(before); after.set('group', 'other')
        with self.assertRaisesRegex(ValueError, 'root metadata'):
            fixture.verify_difference(before, after)

    def test_start_profile_and_wrong_flag_pose_are_rejected(self):
        for name in ('flags', 'position'):
            before, after, spec = self.documents()
            if name == 'flags':
                fixture.fixtures.block(after, 'player starting locations')[0][3].set('value', 'changed')
            else:
                fixture.fixtures.block(after, 'cutscene flags')[0][1].set('value', '1,2,4')
            with self.assertRaises(ValueError):
                fixture.verify_poses(before, after, spec)
        with self.assertRaisesRegex(ValueError, 'Native transform differs'):
            fixture.check_vector([float('nan')], [0], 'invalid')

    def test_startup_requires_exact_script_bytes_line_and_native_name(self):
        before, _, spec = self.documents()
        with tempfile.TemporaryDirectory() as directory:
            h3 = Path(directory); (h3 / 'data').mkdir()
            script = h3 / 'data/start.hsc'
            script.write_bytes(b'; startup\r\n(kill_volume_disable kill_cleanup)\r\n')
            row = dict(name='kill_cleanup', source_script='start.hsc', source_line=2,
                       source_sha256=fixture.digest(script))
            spec['disabled_kill_volumes'] = [row]
            self.assertEqual(fixture.runtime_setup(spec, h3, before), ['(kill_volume_disable kill_cleanup)'])
            for key, value in [('name', 'unknown'), ('source_line', 1), ('source_sha256', 'changed')]:
                altered = deepcopy(spec); altered['disabled_kill_volumes'][0][key] = value
                with self.assertRaises(ValueError):
                    fixture.runtime_setup(altered, h3, before)

    def test_restore_retains_unrecognized_files_and_refuses_changed_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory); h3 = run / 'h3'; reach = run / 'reach'
            for path in (h3 / 'tags', reach / 'tags', reach / 'data'):
                path.mkdir(parents=True)
            paths = fixture.OutputPaths(h3, reach, 'levels/h3_port/fixture')
            target = paths.owned_tag(paths.scenario + '.scenario')
            target.parent.mkdir(parents=True)
            target.write_bytes(b'fixture'); main = reach / 'tags/main.scenario'; main.write_bytes(b'main')
            extra = target.parent / 'user-note.txt'; extra.write_bytes(b'keep')
            manifest = run / 'fixture-manifest.json'
            report = dict(format='foundry.h3-player-interaction-fixture', status='NATIVE_READBACK_VERIFIED',
                h3_root=str(h3), reach_root=str(reach), namespace=paths.namespace,
                fixture_scenario=str(target), fixture_sha256=fixture.digest(target),
                main_scenario=str(main), main_sha256=fixture.digest(main))
            manifest.write_text(json.dumps(report), encoding='utf-8')
            target.write_bytes(b'edited fixture')
            with self.assertRaisesRegex(ValueError, 'Fixture changed'):
                fixture.restore(manifest)
            self.assertTrue(target.exists())
            target.write_bytes(b'fixture'); main.write_bytes(b'edited main')
            with self.assertRaisesRegex(ValueError, 'Main scenario changed'):
                fixture.restore(manifest)
            self.assertTrue(target.exists())
            main.write_bytes(b'main')
            fixture.restore(manifest)
            self.assertFalse(target.exists())
            self.assertEqual(extra.read_bytes(), b'keep')
            self.assertEqual(main.read_bytes(), b'main')


if __name__ == '__main__':
    unittest.main()
