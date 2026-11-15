#!/usr/bin/env python3
"""Offline adversarial matrix for the P06 evidence verifier (no external API)."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('mp12_p06_final_qualification',
    Path(__file__).with_name('mp12_p06_final_qualification.py'))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
HEAD = 'a' * 40
OTHER = 'b' * 40
LOG = ('MP11_P04_KVM_OPEN_PASS\nStarting 5 tests on test(AVD)\n'
       'Finished 5 tests on test(AVD)\n'
       'MP11_P04_API36_FIVE_REAL_COMPOSE_TESTS_PASS_NOT_PHYSICAL_ARM64\n')

def fixtures():
    runs = [dict(id=i+1,name=name,event=event,head_sha=HEAD,
                 status='completed',conclusion='success')
            for i,(_,name,event,_) in enumerate(m.SPECS)]
    jobs = {i+1:[dict(id=100+i,name=spec[3],status='completed',
                      conclusion='success')] for i,spec in enumerate(m.SPECS)}
    return runs,jobs

def ledger(runs=None,jobs=None,log=LOG,head=HEAD,prov='github_verified'):
    r,j=fixtures()
    return m.build_ledger(head,r if runs is None else runs,j if jobs is None else jobs,
                          log,provenance=prov)

class QualificationGates(unittest.TestCase):
    def test_known_good_hosted_fixtures_never_release(self):
        result=ledger()
        self.assertEqual(result['verified_hosted_gate_count'],4)
        self.assertEqual(result['total_gate_count'],11)
        self.assertEqual(result['go_canary_primary'],'legacy')
        for key in ('release_qualified','production_cutover_authorized',
                    'physical_arm64_inferred_from_api36_x86','go_shadow_executes_downloads'):
            self.assertFalse(result[key])
    def test_missing_x86_is_not_inferred_from_compose(self):
        r,j=fixtures();r.pop();o=ledger(r,j)
        self.assertEqual(o['verified_hosted_gate_count'],3)
        self.assertEqual(o['gates']['x86_full_native_api36']['status'],'not_qualified')
    def test_external_axes_always_blocked(self):
        o=ledger()
        for key in m.GATES[4:]: self.assertEqual(o['gates'][key]['status'],'not_qualified')
    def test_synthetic_evidence_cannot_qualify(self):
        o=ledger(prov='synthetic_test_only')
        self.assertEqual(o['verified_hosted_gate_count'],0)
        self.assertFalse(o['release_qualified'])
    def test_malformed_sha_refuses(self):
        for head in ('bad','A'*40,'0'*41,''):
            with self.subTest(head=head),self.assertRaises(m.Refused):ledger(head=head)
    def test_cross_head_replay_refuses(self):
        r,j=fixtures();r[0]['head_sha']=OTHER
        with self.assertRaises(m.Refused):ledger(r,j)
    def test_stale_success_not_mask_new_failure(self):
        r,j=fixtures();r.append(dict(r[0],id=90,conclusion='failure'))
        o=ledger(r,j);self.assertEqual(o['gates']['targeted_source']['status'],'not_qualified')
    def test_stale_success_not_mask_new_pending(self):
        r,j=fixtures();r.append(dict(r[0],id=90,status='in_progress',conclusion=None))
        self.assertEqual(ledger(r,j)['gates']['targeted_source']['status'],'not_qualified')
    def test_duplicate_run_id_global_refuses(self):
        r,j=fixtures();r.append(dict(r[0]))
        with self.assertRaises(m.Refused):ledger(r,j)
    def test_duplicate_job_refuses(self):
        r,j=fixtures();j[1].append(dict(j[1][0],id=500))
        self.assertEqual(ledger(r,j)['gates']['targeted_source']['status'],'not_qualified')
    def test_skipped_job_refuses(self):
        r,j=fixtures();j[1][0]['conclusion']='skipped'
        self.assertEqual(ledger(r,j)['verified_hosted_gate_count'],3)
    def test_job_wrong_identity_refuses(self):
        r,j=fixtures();j[1][0]['name']='lookalike'
        self.assertEqual(ledger(r,j)['verified_hosted_gate_count'],3)
    def test_negative_job_id_refuses(self):
        r,j=fixtures();j[1][0]['id']=-1
        self.assertEqual(ledger(r,j)['verified_hosted_gate_count'],3)
    def test_run_wrong_event_refuses(self):
        r,j=fixtures();r[0]['event']='push'
        self.assertEqual(ledger(r,j)['verified_hosted_gate_count'],3)
    def test_workflow_wrong_name_refuses(self):
        r,j=fixtures();r[0]['name']='fake source'
        self.assertEqual(ledger(r,j)['verified_hosted_gate_count'],3)
    def test_oversized_list_refuses(self):
        r,j=fixtures();r.extend(dict(id=500+i,name='other',head_sha=HEAD) for i in range(100))
        with self.assertRaises(m.Refused):ledger(r,j)
    def test_invalid_provenance_refuses(self):
        with self.assertRaises(m.Refused):ledger(prov='force_release')
    def test_missing_compose_marker_not_qualified(self):
        for part in ('MP11_P04_KVM_OPEN_PASS','Starting 5 tests on','Finished 5 tests on',
                     'MP11_P04_API36_FIVE_REAL_COMPOSE_TESTS_PASS_NOT_PHYSICAL_ARM64'):
            with self.subTest(part=part):
                o=ledger(log=LOG.replace(part,''))
                self.assertEqual(o['gates']['mp11_p04_compose_api36']['status'],'not_qualified')
    def test_fake_one_test_not_qualified(self):
        o=ledger(log=LOG.replace('5 tests','1 tests'))
        self.assertEqual(o['gates']['mp11_p04_compose_api36']['status'],'not_qualified')
    def test_duplicates_actual_count_refuse(self):
        o=ledger(log=LOG+LOG)
        self.assertEqual(o['gates']['mp11_p04_compose_api36']['status'],'not_qualified')
    def test_kvm_logged_twice_is_allowed(self):
        self.assertTrue(m.compose_markers_pass(LOG+'MP11_P04_KVM_OPEN_PASS\n'))
    def test_false_booleans_not_identifiers(self):
        r,j=fixtures();r[0]['id']=True
        with self.assertRaises(m.Refused):ledger(r,j)
    def test_jobs_paged_refuse(self):
        r,j=fixtures();j[1]=j[1]*101
        with self.assertRaises(m.Refused):ledger(r,j)
    def test_report_closed_set_only_redacted(self):
        out=json.dumps(ledger())
        for word in ('cookie','password','token','device_serial','http://'):
            self.assertNotIn(word,out)
    def test_report_private_create_no_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/'report.json'
            m.private_write(f,ledger())
            self.assertEqual(f.stat().st_mode & 0o777,0o600)
            with self.assertRaises(m.Refused):m.private_write(f,ledger())
    def test_report_symlink_refuses(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'a';b=Path(t)/'b';a.write_text('untouched')
            b.symlink_to(a)
            with self.assertRaises(m.Refused):m.private_write(b,ledger())
            self.assertEqual(a.read_text(),'untouched')

class PhysicalReadOnly(unittest.TestCase):
    def fake_adb(self,serial='localhost:5555',abi='arm64-v8a,armeabi-v7a',qemu='0',sdk='36'):
        def runner(cmd, timeout=60):
            self.assertEqual(cmd[:3],['adb','-s',serial])
            if cmd[3:] == ['get-state']: return 'device\n'
            key=cmd[-1]
            return {'ro.build.version.sdk':sdk,'ro.product.cpu.abilist':abi,
                    'ro.product.cpu.abi':'arm64-v8a','ro.kernel.qemu':qemu}[key]+'\n'
        return runner
    def test_physical_preflight_does_not_qualify(self):
        with patch.object(m,'_run',side_effect=self.fake_adb()):
            out=m.inspect_physical('localhost:5555')
            self.assertFalse(out['physical_arm64_media_qualified'])
            self.assertFalse(out['instrumentation_executed'])
            self.assertFalse(out['device_identifier_recorded'])
    def test_physical_emulator_refuses(self):
        with patch.object(m,'_run',side_effect=self.fake_adb(qemu='1')):
            with self.assertRaises(m.Refused):m.inspect_physical('localhost:5555')
    def test_physical_invalid_sdk_refuses(self):
        with patch.object(m,'_run',side_effect=self.fake_adb(sdk='25')):
            with self.assertRaises(m.Refused):m.inspect_physical('localhost:5555')
    def test_physical_wrong_abi_refuses(self):
        with patch.object(m,'_run',side_effect=self.fake_adb(abi='x86_64')):
            with self.assertRaises(m.Refused):m.inspect_physical('localhost:5555')
    def test_physical_injection_serial_refuses(self):
        with self.assertRaises(m.Refused):m.inspect_physical('a;sh -c reboot')
    def test_physical_unknown_qemu_refuses(self):
        with patch.object(m,'_run',side_effect=self.fake_adb(qemu='unknown')):
            with self.assertRaises(m.Refused):m.inspect_physical('localhost:5555')

class SourceMutation(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix='mp12-p06-policy-')
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.samples={
            '.github/workflows/android.yml':"name: test\n  signed-release:\n    if: startsWith(github.ref, 'refs/tags/android-v')\n    XDM_XAR16_FULL_RELEASE_GATE XDM_RELEASE_SIGNER_SHA256\n    run-hosted-emulator-instrumentation.sh --signed-release\n    xdm-android-signed-release\n  emulator-compatibility:\n",
            '.github/workflows/xgo-x86-native-media.yml':"types: [labeled]\ngithub.event.label.name == 'xgo-x86-native-media'\ngithub.event.pull_request.head.repo.full_name == github.repository",
            'scripts/run_physical_arm64_instrumentation.sh':"ro.kernel.qemu\nXGO_ADB_EMULATOR_REFUSED\nXGO_ADB_NATIVE_ARM64_REQUIRED\nINSTRUMENTATION_CODE: -1\nXGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS",
            'engine/runtime/canary/controller.go':"ProductionCutoverAuthorized: false Primary: \"legacy\" UnsafePromotion() os.O_EXCL func Open(",
            'scripts/mp12_p05_desktop_parity.py':'ProtocolVersion = "2.0"',
            'scripts/mp12_p04_signed_release.py':'SOURCE_PINS publication_automatically_authorized',
            'scripts/mp12_p02_provenance.py':'release_eligible',
        }
        for path in m.SOURCE_PINS:
            s=self.samples.get(path,'pinned-source')
            f=self.root/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(s)
        self.pins={path:m.blob((self.root/path).read_bytes()) for path in m.SOURCE_PINS}
    def audit(self):return m.source_guard(self.root,self.pins)
    def test_valid_fixture(self):
        self.assertEqual(self.audit()['checked_source_git_blobs'],len(self.pins))
    def test_all_twelve_pins_fail_on_mutation(self):
        for path in m.SOURCE_PINS:
            f=self.root/path;old=f.read_bytes();f.write_bytes(old+b'\ndrift')
            with self.subTest(path=path),self.assertRaises(m.Refused):self.audit()
            f.write_bytes(old)
    def test_signed_job_mutation_refuses(self):
        p='.github/workflows/android.yml';f=self.root/p
        f.write_text(self.samples[p].replace('android-v','unsafe-v'))
        self.pins[p]=m.blob(f.read_bytes())
        with self.assertRaises(m.Refused):self.audit()
    def test_canary_promotion_mutation_refuses(self):
        p='engine/runtime/canary/controller.go';f=self.root/p
        f.write_text(self.samples[p].replace('false','true'))
        self.pins[p]=m.blob(f.read_bytes())
        with self.assertRaises(m.Refused):self.audit()
    def test_x86_optin_removed_refuses(self):
        p='.github/workflows/xgo-x86-native-media.yml';f=self.root/p
        f.write_text(self.samples[p].replace('types: [labeled]','types: [synchronize]'))
        self.pins[p]=m.blob(f.read_bytes())
        with self.assertRaises(m.Refused):self.audit()
    def test_symlink_refuses_even_matching_content(self):
        p=self.root/'scripts/mp12_p02_provenance.py';bytes_=p.read_bytes()
        p.unlink();q=self.root/'original';q.write_bytes(bytes_);p.symlink_to(q)
        with self.assertRaises(m.Refused):self.audit()

if __name__ == '__main__':
    unittest.main(verbosity=2)
