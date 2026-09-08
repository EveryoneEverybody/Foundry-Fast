"""A range value must not erase the source attenuation enable switch."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_environment_emission import attenuation_enablement


class EmissionEnablementAudit(unittest.TestCase):
    def test_disabled_source_is_not_called_equivalent_to_enabled_export(self):
        result = attenuation_enablement(['0', '0'], [1])
        self.assertEqual(result['source_use_attenuation'], [False])
        self.assertEqual(result['status'], 'TARGET_DISABLED_BEHAVIOR_REQUIRES_VERIFICATION')
        self.assertFalse(result['numeric_range_equality_proves_enablement'])

    def test_enabled_source_and_export_agree_without_inferring_photometry(self):
        result = attenuation_enablement(['1'], [1])
        self.assertEqual(result['status'], 'ENABLEMENT_MATCH')
        self.assertEqual(result['native_bit_zero'], 'reserved{use attenuation}')


if __name__ == '__main__':
    unittest.main()
