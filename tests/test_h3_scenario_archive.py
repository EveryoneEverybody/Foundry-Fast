"""Chunk validation, query coverage, and source retention without full expansion."""
import base64
from copy import deepcopy
import gzip
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from h3_scenario_fixture import inventory, write_bundle
from h3_scenario_archive_fixture import write_archive
from test_h3_scenario_scene import m, PKG

archive = importlib.import_module(PKG + '.scenario_archive')
inspection = m.inspection


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _, self.original = write_bundle(self.root, with_blob=True)
        self.manifest = write_archive(self.root, self.original)
        self.path = self.root / 'scenario.h3inspect.json'

    def save(self):
        self.path.write_text(json.dumps(self.manifest))

    def test_lossless_record_order_flags_and_source_coordinates(self):
        data = inspection.load(self.path)
        self.assertEqual(list(inspection.iter_records(data)), self.original['records'])
        self.assertNotIn('records', data)
        self.assertEqual(m.hint_plan(data), m.hint_plan(self.original))
        self.assertEqual(json.loads(json.dumps(data)), self.manifest)

    def test_selective_query_does_not_drop_other_sections(self):
        row = dict(address='compiled#99[0]/value#0', name='retained', raw_name='retained',
                   ordinal=0, type='long integer', kind='value', value=101)
        original = deepcopy(self.original)
        original['records'].append(row)
        write_archive(self.root, original)
        data = inspection.load(self.path)
        self.assertEqual(inspection.named_fields(data, 'retained'), [row])
        self.assertEqual(m.hint_plan(data), m.hint_plan(self.original))
        self.assertEqual(list(inspection.iter_records(data, roots={'compiled'})), [row])

    def test_duplicate_address_across_chunks_rejected(self):
        original = deepcopy(self.original)
        original['records'].append(deepcopy(original['records'][1]))
        write_archive(self.root, original, per_chunk=1)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            inspection.load(self.path)

    def test_reference_stays_queryable(self):
        original = deepcopy(self.original)
        reference = dict(group=0x73627370, path='levels/a.001', extension='scenario_structure_bsp')
        original['records'].append(dict(address='bsps#9', name='bsps', raw_name='bsps', ordinal=9,
                                        type='tag reference', kind='value', value=reference))
        write_archive(self.root, original)
        data = inspection.load(self.path)
        self.assertEqual(inspection.dependency_requests(data, 'scenario_structure_bsp'),
                         [dict(address='bsps#9', source_tag='levels/a.001.scenario_structure_bsp', source_group=0x73627370)])

    def test_corrupt_compressed_file_rejected(self):
        path = self.root / self.manifest['chunks'][0]['file']
        content = bytearray(path.read_bytes())
        content[-8] ^= 1
        path.write_bytes(content)
        with self.assertRaises(ValueError):
            inspection.load(self.path)

    def test_changed_chunk_rejected_during_retention(self):
        data = inspection.load(self.path)
        chunk = data['chunks'][0]
        path = self.root / chunk['file']
        raw = bytearray(path.read_bytes())
        raw[4] ^= 1  # Valid gzip header change, detected by the verified file hash.
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'changed'):
            data.chunk_bytes(chunk)

    def test_truncated_chunk_rejected(self):
        path = self.root / self.manifest['chunks'][0]['file']
        path.write_bytes(path.read_bytes()[:-8])
        with self.assertRaises(ValueError):
            inspection.load(self.path)

    def test_chunk_cannot_escape_root(self):
        self.manifest['chunks'][0]['file'] = '../outside.gz'
        self.save()
        with self.assertRaises(ValueError):
            inspection.load(self.path)

    def test_chunk_symlink_escape_rejected(self):
        path = self.root / self.manifest['chunks'][0]['file']
        with tempfile.TemporaryDirectory() as other:
            target = Path(other) / 'outside.gz'
            target.write_bytes(path.read_bytes())
            path.unlink()
            try:
                path.symlink_to(target)
            except OSError:
                self.skipTest('Symlinks unavailable')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                inspection.load(self.path)

    def test_count_byte_and_reference_summaries_checked(self):
        original = deepcopy(self.manifest)
        for name in ('record_count', 'raw_bytes', 'compressed_bytes', 'reference_count', 'blob_count', 'blob_bytes'):
            self.manifest = deepcopy(original)
            self.manifest[name] += 1
            self.save()
            with self.subTest(name=name), self.assertRaises(ValueError):
                inspection.load(self.path)

    def test_boolean_counts_rejected(self):
        self.manifest['record_count'] = True
        self.save()
        with self.assertRaises(ValueError):
            inspection.load(self.path)

    def test_decompression_budget_checked(self):
        self.manifest['chunks'][0]['raw_bytes'] = archive.CHUNK_BYTES + 1
        self.save()
        with self.assertRaises(ValueError):
            inspection.load(self.path)

    def test_wrong_section_assignment_rejected(self):
        self.manifest['chunks'][0]['root_address'] = 'other#0'
        self.save()
        with self.assertRaises(ValueError):
            inspection.load(self.path)

    def test_duplicate_chunk_paths_rejected(self):
        self.manifest['chunks'][1]['file'] = self.manifest['chunks'][0]['file']
        self.save()
        with self.assertRaises(ValueError):
            inspection.load(self.path)

    def test_invalid_row_still_rejected(self):
        original = deepcopy(self.original)
        original['records'][1]['ordinal'] = -1
        write_archive(self.root, original)
        with self.assertRaises(ValueError):
            inspection.load(self.path)

    def test_diagnostics_are_retained_and_counted(self):
        original = deepcopy(self.original)
        original['records'].extend([
            dict(address='resource#91', name='resource', raw_name='resource', ordinal=91,
                 type='resource', kind='resource_header_only'),
            dict(address='unknown#92', name='unknown', raw_name='unknown', ordinal=92,
                 type='unknown', kind='value', value=dict(representation='decoder_debug', value='original'))])
        write_archive(self.root, original)
        data = inspection.load(self.path)
        self.assertEqual(len(data['diagnostics']), 2)
        self.assertEqual(inspection.named_fields(data, 'unknown')[-1]['value']['value'], 'original')

    def test_legacy_inventory_remains_supported(self):
        self.path.write_text(json.dumps(self.original))
        self.assertEqual(inspection.load(self.path), self.original)

    def test_packed_query_survives_removal_of_extraction(self):
        data = inspection.load(self.path)
        entries, texts = [], {}
        for chunk in data['chunks']:
            content = data.chunk_bytes(chunk)
            name = chunk['file']
            texts[name] = base64.b64encode(content).decode('ascii')
            entries.append(dict(file=chunk['file'], text=name, encoding='gzip+base64',
                                sha256=hashlib.sha256(content).hexdigest()))
        self.temp.cleanup()
        retained = archive.from_packed(dict(data), entries, texts.__getitem__)
        self.assertEqual(list(inspection.iter_records(retained)), self.original['records'])
        self.assertEqual(m.hint_plan(retained), m.hint_plan(self.original))
        texts[entries[0]['text']] = 'broken'
        with self.assertRaises(ValueError):
            archive.from_packed(dict(data), entries, texts.__getitem__)


if __name__ == '__main__':
    unittest.main()
