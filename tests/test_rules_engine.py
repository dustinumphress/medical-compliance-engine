import sys
import os
sys.path.append(os.getcwd())

import unittest
from execution.rules_engine import RulesEngine, CPT_RULES

class TestRulesEngine(unittest.TestCase):

    def test_15730_midface(self):
        # Valid
        valid = "A zygomatico-facial flap was raised with preservation of the vascular pedicle."
        status, reason = RulesEngine.validate("15730", valid)
        self.assertEqual(status, "PASS", f"Failed Valid 15730: {reason}")

        # Invalid (Keywords)
        invalid_kw = "A skin flap was moved on the cheek."
        status, reason = RulesEngine.validate("15730", invalid_kw)
        self.assertEqual(status, "FAIL", "Should fail due to missing Midface/Vascular keywords")

        # Exclusion (Cosmetic Lift)
        exclusion = "Midface lift performed for aesthetic rejuvenation."
        status, reason = RulesEngine.validate("15730", exclusion)
        self.assertEqual(status, "HARD_FAIL")
        self.assertIn("excluded term", reason.lower())

    def test_15733_head_neck(self):
        # Valid (Temporalis)
        valid = "The Temporalis muscle was transposed."
        status, reason = RulesEngine.validate("15733", valid)
        self.assertEqual(status, "PASS")

        # Invalid (Platysma - Exclusion)
        platysma = "A Platysma muscle flap was used."
        status, reason = RulesEngine.validate("15733", platysma)
        self.assertEqual(status, "HARD_FAIL", "Platysma should be HARD FAIL")

        # Invalid (Missing Finite List)
        missing = "A generic neck muscle was moved."
        status, reason = RulesEngine.validate("15733", missing)
        self.assertEqual(status, "FAIL", "Should fail if not in finite list")

    def test_15734_trunk(self):
        # Valid
        valid = "Dissection carried down to deep fascia. Latissimus dorsi myocutaneous flap elevated."
        status, reason = RulesEngine.validate("15734", valid)
        self.assertEqual(status, "PASS")

        # Valid Synonym (Sub-fascial)
        valid_syn = "Sub-fascial plane entered. Flap rotated."
        status, reason = RulesEngine.validate("15734", valid_syn)
        self.assertEqual(status, "PASS")

        # Exclusion (Component Separation w/o Flap)
        comp_sep = "Component separation technique performed. Posterior sheath released."
        status, reason = RulesEngine.validate("15734", comp_sep)
        self.assertEqual(status, "HARD_FAIL", "Comp Sep w/o Flap should fail")

        # Component Separation WITH flap language is allowed ('unless' clause)
        comp_sep_ok = "Component separation performed, then myocutaneous flap rotated over deep fascia."
        status, reason = RulesEngine.validate("15734", comp_sep_ok)
        self.assertEqual(status, "PASS", f"Comp Sep with flap should pass: {reason}")

    def test_15736_arm(self):
        valid = "A fasciocutaneous flap was elevated on the upper arm."
        status, reason = RulesEngine.validate("15736", valid)
        self.assertEqual(status, "PASS")

        invalid = "A skin flap was advanced on the arm."
        status, reason = RulesEngine.validate("15736", invalid)
        self.assertEqual(status, "FAIL", "Should detect missing deep fascia / fasciocutaneous")

    def test_15738_leg(self):
        # Valid
        valid = "Deep fascia included in the flap. Used for limb salvage of open fracture."
        status, reason = RulesEngine.validate("15738", valid)
        self.assertEqual(status, "PASS")

        # Invalid (No deep fascia)
        invalid = "Skin flap rotated over the defect on the leg."
        status, reason = RulesEngine.validate("15738", invalid)
        self.assertEqual(status, "FAIL", "Should detect missing deep fascia")

    def test_unknown_code_defaults_to_pass(self):
        status, reason = RulesEngine.validate("99999", "Any text at all.")
        self.assertEqual(status, "PASS")
        self.assertIsNone(reason)

    def test_code_normalization(self):
        # Integers and padded strings should dispatch to the same rule
        status, _ = RulesEngine.validate(15733, "Temporalis muscle used.")
        self.assertEqual(status, "PASS")
        status, _ = RulesEngine.validate(" 15733 ", "Temporalis muscle used.")
        self.assertEqual(status, "PASS")

    def test_exclusion_outranks_requirements(self):
        # Text satisfies every 15730 requirement but contains a cosmetic term
        text = "Midface flap with vascular pedicle preserved, for aesthetic improvement."
        status, reason = RulesEngine.validate("15730", text)
        self.assertEqual(status, "HARD_FAIL")

    def test_rules_data_shape(self):
        # Guard the data structure so a malformed rule fails loudly in CI
        for code, rule in CPT_RULES.items():
            self.assertTrue(rule.get("exclusions") or rule.get("requirements"),
                            f"{code}: rule has no checks")
            for exc in rule.get("exclusions", []):
                self.assertIn("pattern", exc, f"{code}: exclusion missing pattern")
            for req in rule.get("requirements", []):
                self.assertIn("pattern", req, f"{code}: requirement missing pattern")
                self.assertTrue(req.get("message"), f"{code}: requirement missing message")

if __name__ == '__main__':
    unittest.main()
