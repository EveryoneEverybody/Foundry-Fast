"""Preservation gates for rebaking accepted native environments."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'blender/addons/io_scene_foundry/h3_import'))
from port_environment.runtime_bake import require_parent


class BakePreservation(unittest.TestCase):
    def test_exact_ownership_and_external_read_only_additions(self):
        owned = {'tags/bsp.scenario_structure_bsp': 'accepted'}
        external = {'data/preview.tiff': 'user'}
        require_parent({**owned, **external}, owned, external)
        self.assertEqual(owned, {'tags/bsp.scenario_structure_bsp': 'accepted'})

    def test_external_evidence_cannot_authorize_changed_owned_collision(self):
        with self.assertRaisesRegex(ValueError, 'override'):
            require_parent({'collision': 'edited'}, {'collision': 'accepted'}, {'collision': 'edited'})

    def test_missing_changed_and_new_outputs_reject(self):
        owned = {'collision': 'accepted'}
        external = {'preview': 'user'}
        for actual in ({'collision': 'edited', **external}, external, owned,
                       {**owned, 'preview': 'changed'}, {**owned, **external, 'unknown': 'file'}):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                require_parent(actual, owned, external)


if __name__ == '__main__':
    unittest.main()
