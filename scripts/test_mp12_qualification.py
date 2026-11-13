#!/usr/bin/env python3
"""Mutation and fail-closed tests for source- and SHA-bound MP12 readiness."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('mp12_qualification',
    Path(__file__).with_name('mp12_qualification.py'))
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
SHA = 'c'*40
OTHER = 'd'*40

def fakes(sha=SHA, success=True):
    specs = (
        (1,'XGO Targeted CI','pull_request',module.SOURCE_JOB),
        (2,'XGO MP08B3 Real Media Acceptance','pull_request',module.MP08_JOB),
        (3,'XDM MP00 Media Parity Baseline','workflow_dispatch',module.P04_JOB),
        (4,'XGO x86_64 Native Media Runtime (opt-in only)','pull_request',module.X86_JOB),
    )
    runs = [dict(id=rid,name=name,head_sha=sha,event=event,status='completed',
                 conclusion='success' if success else 'failure')
            for rid,name,event,_ in specs]
    jobs = {rid:[dict(id=rid+100,name=job,status='completed',
                      conclusion='success' if success else 'failure')]
            for rid,_,_,job in specs}
    log='MP11_P04_KVM_OPEN_PASS\nStarting 5 tests on test(AVD)\nFinished 5 tests on test(AVD)\n'+module.P04_MARK
    return runs,jobs,log

class GateTests(unittest.TestCase):
    def test_exact_five_real_results_and_manual_blockers(self):
        runs,jobs,log=fakes()
        out=module.build_ledger(SHA,runs,jobs,log)
        self.assertEqual(out['verified_gate_count'],4)
        self.assertEqual(out['gate_count'],11)
        self.assertFalse(out['release_qualified'])
        self.assertEqual(out['gates']['mp11_p04_compose_api36']['status'],'verified')
        self.assertEqual(out['gates']['physical_arm64_media']['status'],'not_qualified')
        self.assertFalse(out['physical_arm64_inferred_from_x86'])
    def test_no_stale_cross_sha_evidence(self):
        runs,jobs,log=fakes(OTHER)
        out=module.build_ledger(SHA,runs,jobs,log)
        self.assertEqual(out['verified_gate_count'],0)
    def test_no_p04_without_true_five_case_receipt(self):
        runs,jobs,log=fakes()
        for token in (module.P04_MARK, module.P04_STARTED,module.P04_FINISHED,'MP11_P04_KVM_OPEN_PASS'):
            out=module.build_ledger(SHA,runs,jobs,log.replace(token,''))
            self.assertEqual(out['gates']['mp11_p04_compose_api36']['status'],'not_qualified')
    def test_never_equate_compile_with_api36(self):
        runs,jobs,log=fakes()
        jobs[3][0]['conclusion']='skipped'
        out=module.build_ledger(SHA,runs,jobs,log)
        self.assertNotEqual(out['gates']['mp11_p04_compose_api36']['status'],'verified')
    def test_wrong_event_or_missing_job_refuses(self):
        runs,jobs,log=fakes()
        runs[2]['event']='push'
        self.assertEqual(module.build_ledger(SHA,runs,jobs,log)['gates']['mp11_p04_compose_api36']['status'],'not_qualified')
        runs[2]['event']='workflow_dispatch'
        jobs[3]=[]
        self.assertEqual(module.build_ledger(SHA,runs,jobs,log)['gates']['mp11_p04_compose_api36']['status'],'not_qualified')
    def test_malformed_or_duplicate_source_gate(self):
        runs,jobs,log=fakes()
        with self.assertRaises(module.Refused): module.build_ledger('short',runs,jobs,log)
        jobs[1].append(dict(jobs[1][0]))
        self.assertNotEqual(module.build_ledger(SHA,runs,jobs,log)['gates']['targeted_source']['status'],'verified')
    def test_latest_run_failure_not_masked_by_old_green(self):
        runs,jobs,log=fakes()
        runs.append(dict(runs[0],id=40,conclusion='failure'))
        self.assertEqual(module.build_ledger(SHA,runs,jobs,log)['gates']['targeted_source']['status'],'not_qualified')
    def test_source_policy_mutations_fail_closed(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            pieces={
             'app/XDM.Android/app/build.gradle.kts':'abiFilters += setOf("arm64-v8a")',
             '.github/workflows/xgo-mp08b3-acceptance.yml': 'x86_64_media_test:\n  description: only opt in\n  default: false\n',
             '.github/workflows/xgo-x86-native-media.yml': "types: [labeled]\ngithub.event.label.name == 'xgo-x86-native-media'\ngithub.event.pull_request.head.repo.full_name == github.repository",
             '.github/workflows/media-parity.yml': "mp11-p04-api36-registered:\ngithub.event_name == 'workflow_dispatch'\ntest \"$pr_head\" = \"$EXPECTED_SHA\"\npython3 -B scripts/test_mp11_p04_instrumentation.py --api36-execute",
             'scripts/run_physical_arm64_instrumentation.sh':'ro.kernel.qemu\nXGO_ADB_EMULATOR_REFUSED\nXGO_ADB_NATIVE_ARM64_REQUIRED',
             '.github/workflows/xgo-targeted.yml':'NOT full qualification\ntargeted-qualification:',
            }
            for name,txt in pieces.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(txt)
            self.assertEqual(len(module.source_guard(root)),6)
            p=root/'app/XDM.Android/app/build.gradle.kts';p.write_text('abiFilters += setOf("x86_64")')
            with self.assertRaises(module.Refused):module.source_guard(root)
            p.write_text(pieces['app/XDM.Android/app/build.gradle.kts'])
            p=root/'.github/workflows/xgo-mp08b3-acceptance.yml';p.write_text(pieces['.github/workflows/xgo-mp08b3-acceptance.yml'].replace('default: false','default: true'))
            with self.assertRaises(module.Refused):module.source_guard(root)

    def test_mp12_p02_native_provenance_source_and_negative_matrix(self):
        # MP12 P01's already-registered source lane executes P02 without
        # altering the immutably pinned historical CI05 workflow again.
        import subprocess
        p02 = Path(__file__).with_name('test_mp12_p02_provenance.py')
        guard = Path(__file__).with_name('mp12_p02_provenance.py')
        self.assertTrue(p02.is_file())
        self.assertTrue(guard.is_file())
        for command in ((sys.executable, '-B', str(p02)),
                        (sys.executable, '-B', str(guard), 'source-only',
                         '--repo', str(Path(__file__).resolve().parents[1]))):
            proc = subprocess.run(command, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  timeout=90, check=False)
            self.assertEqual(proc.returncode, 0, proc.stdout[-2000:])

    def test_mp12_p03_durable_legacy_canary_contracts(self):
        # Source- and fixture-level canary tests run in the pre-existing MP12 P01
        # targeted lane, without weakening any historical exact CI05 workflow.
        import subprocess
        script = Path(__file__).with_name('test_mp12_p03_canary_contract.py')
        self.assertTrue(script.is_file())
        p = subprocess.run([sys.executable, '-B', str(script)],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=90, check=False)
        self.assertEqual(p.returncode, 0, p.stdout[-2400:])

if __name__ == '__main__':
    unittest.main(verbosity=2)
