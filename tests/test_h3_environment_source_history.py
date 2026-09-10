"""Historical asset evidence cannot become a runtime texture substitution."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from test_h3_environment_dependencies import fixture, SHADER, MISSING, RUNTIME
from port_environment import source_history
from port_environment.dependencies import audit
from port_environment.paths import digest


def history(directory, identity=MISSING):
    path=Path(directory)/'historical-source.fixture'
    path.write_bytes(b'Synthetic history evidence, no proprietary image data')
    return dict(format='h3_authoring_source_history',version=1,records=[dict(
        source_bitmap=identity+'.bitmap',classification='HISTORICAL_H3_AUTHORING_ASSET',
        assertion='Community confirms the historical source identity and a matching supplied copy',
        evidence_kind='USER_RELAYED_COMMUNITY_CONFIRMATION_AND_SUPPLIED_ARTIFACT',
        confidence='COMMUNITY_CONFIRMED_HISTORY_LOCAL_ARTIFACT_HASH_VERIFIED',
        verification_limit='The historical original was not independently compared',
        allowed_use='SOURCE_HISTORY_OR_OPTIONAL_FUTURE_AUTHORING_RECONSTRUCTION',runtime_binding_authority=False,
        artifact=dict(path=str(path),sha256=digest(path),bytes=path.stat().st_size))])


class SourceHistory(unittest.TestCase):
    def test_historical_identity_does_not_change_verified_retail_bitmap_uv_or_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            m,b,s,inventory,cache=fixture(directory);original=deepcopy(m)
            effective,report=audit(m,[b],[],s,inventory,[cache])
            shader=deepcopy(effective['shaders'][SHADER]);pixels=deepcopy(effective['bitmaps'])
            overrides=deepcopy(report['runtime_binding_overrides'])
            document=history(directory);before=deepcopy(document)
            source_history.annotate(report,document)
            row=next(r for r in report['missing_references'] if r['source_bitmap']==MISSING+'.bitmap')
            self.assertEqual(row['classification'],'HISTORICAL_AUTHORING_REFERENCE_VERIFIED_RUNTIME_BINDING')
            self.assertEqual(row['runtime_resolution_classification'],'STALE_LOOSE_REFERENCE_VERIFIED_RUNTIME_BINDING')
            self.assertEqual(row['source_history']['artifact_verification'],'LOCAL_FILE_HASH_VERIFIED')
            self.assertEqual(effective['shaders'][SHADER],shader);self.assertEqual(effective['bitmaps'],pixels)
            self.assertEqual(report['runtime_binding_overrides'],overrides)
            self.assertEqual(m,original);self.assertEqual(document,before)
            self.assertEqual(effective['shaders'][SHADER]['parameters'][0]['bitmap'],RUNTIME+'#0')
            self.assertFalse(report['unsupported'])
            annotated=deepcopy(report);source_history.annotate(report,document)
            self.assertEqual(report,annotated)

    def test_history_without_verified_runtime_binding_cannot_clear_dependency_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            m,b,s,inventory,_=fixture(directory)
            effective,report=audit(m,[b],[],s,inventory)
            before=deepcopy(report['unsupported']);classification=report['missing_references'][-1]['classification']
            source_history.annotate(report,history(directory))
            self.assertEqual(report['unsupported'],before);self.assertTrue(before)
            self.assertEqual(report['missing_references'][-1]['classification'],classification)
            self.assertEqual(effective['shaders'][SHADER]['parameters'][0]['bitmap'],MISSING+'#0')

    def test_similar_name_does_not_establish_exact_history_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            m,b,s,inventory,cache=fixture(directory)
            _,report=audit(m,[b],[],s,inventory,[cache])
            source_history.annotate(report,history(directory,'elsewhere/missing_normal'))
            self.assertFalse(any('source_history' in r for r in report['missing_references']))
            self.assertEqual(report['source_history']['unmatched_identities'],['elsewhere/missing_normal.bitmap'])

    def test_changed_historical_file_fails_before_report_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            m,b,s,inventory,cache=fixture(directory)
            _,report=audit(m,[b],[],s,inventory,[cache]);before=deepcopy(report)
            document=history(directory);Path(document['records'][0]['artifact']['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'recorded bytes'):source_history.annotate(report,document)
            self.assertEqual(report,before)

    def test_history_cannot_request_runtime_authority_or_hide_verification_limits(self):
        for change in ('authority','limits','duplicate'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                m,b,s,inventory,cache=fixture(directory)
                _,report=audit(m,[b],[],s,inventory,[cache]);before=deepcopy(report)
                document=history(directory)
                if change=='authority':document['records'][0]['runtime_binding_authority']=True
                elif change=='limits':document['records'][0].pop('verification_limit')
                else:document['records'].append(deepcopy(document['records'][0]))
                with self.assertRaises(ValueError):source_history.annotate(report,document)
                self.assertEqual(report,before)


if __name__=='__main__':unittest.main()
