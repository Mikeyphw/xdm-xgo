#!/usr/bin/env python3
"""MP03 anti-staleness: exact existing contracts and immutable XPI must still match current tree."""
from pathlib import Path
import os
import json
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
PINNED_PARENT='8471707c742ef991747ece24b7e03f9c8ccd921d'
REF='docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'

class MP03StaleContract(unittest.TestCase):
    def test_historical_xpi_provenance_unmodified(self):
        expected=subprocess.check_output(['git','show',f'{PINNED_PARENT}:{REF}'],cwd=Path(os.environ.get("XGO_MP03_REAL_REPO", str(ROOT))))
        present=(ROOT/REF).read_bytes()
        self.assertEqual(json.loads(present),json.loads(expected),'Historical and active XPI SHA tables must be retained')
    def test_ci05_unchanged_cadence_and_gate(self):
        s=(ROOT/'scripts/ci/xgo_ci_policy.py').read_text()
        self.assertIn('DEFAULT_INTERVAL = 5',s)
        self.assertIn('"high_risk": any(is_risk(p)',s)
        self.assertIn('if planned["needs_go"]:',s)
        router=(ROOT/'.github/workflows/xgo-full-gate-router.yml').read_text()
        self.assertIn("XGO_FULL_GATE_INTERVAL || '5'",router)
        self.assertIn('needs.gate-plan.outputs.due',router)
        self.assertTrue((ROOT/'.github/workflows/xgo-targeted.yml').is_file())
    def test_existing_security_tests_not_displaced(self):
        p=(ROOT/'scripts/ci/xgo_ci_policy.py').read_text()
        for name in ('test_mp02c_playback.js','test_mp02c_observer.js',
                     'test_xgo_mp02c_staleness_audit.py', 'test_xgo_mp02b_source_contract.py',
                     'test_xgo_mp01_hf05_xpi_guard.py','test_xgo_mp01_hf06_capture_contract.py'):
            self.assertIn(name,p)
    def test_resolver_and_fixture_unconditionally_exercised_in_targeted_ci(self):
        p=(ROOT/'scripts/ci/xgo_ci_policy.py').read_text()
        self.assertIn('"go" in groups',p)
        self.assertIn('tests.update(MP03_PYTHON)',p)
        self.assertIn('scripts/test_xgo_mp03_staleness_contract.py',p)
        self.assertIn('"engine/", "tools/xgo/"',p)

if __name__=='__main__':unittest.main(verbosity=2)
