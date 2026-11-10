#!/usr/bin/env python3
"""MP07 DASH staged multi-period safety and CI05 positive/negative contracts."""
from __future__ import annotations
import re
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT/'engine/media/dash_period_session.go'
TST = ROOT/'engine/media/dash_period_session_test.go'
POLICY = ROOT/'scripts/ci/xgo_ci_policy.py'

def compact(text):
    return re.sub(r'\s+', '', text)

class MP07Source(unittest.TestCase):
    def test_explicit_period_order_and_exact_representation(self):
        c = compact(SRC.read_text())
        for anchor in ('sel.PeriodID != period.ID',
                       'seenPeriod[period.ID]',
                       'a.ID != choice.AdaptationID',
                       'a.Representations[ri].ID != choice.RepresentationID',
                       'f.PeriodID == period.ID',
                       'f.AdaptationID == choice.AdaptationID',
                       'f.RepresentationID == choice.RepresentationID',
                       'mp07Abs(begin-prevEnd)',
                       'mp07Abs((prevEnd-first)-periodMS)',
                       'mp07MaxTotalFragments'):
            self.assertIn(compact(anchor), c, anchor)
    def test_drm_and_missing_required_content_fail_closed(self):
        c = compact(SRC.read_text())
        for anchor in ('mergeDASHProtection(adaptation.Protection, matching.Protection) != DASHProtectionClear',
                       'needInit && strings.TrimSpace(f.InitializationURL) == ""',
                       'else if req.RequireAudio',
                       'if len(fragments) == 0',
                       'if sel.Subtitle.set()',
                       'if dynamic && (req.DynamicPollBound < 1',
                       'if !dynamic && req.DynamicPollBound != 0'):
            self.assertIn(compact(anchor),c,anchor)
    def test_receipts_never_claim_completed_download(self):
        s = SRC.read_text()
        c = compact(s)
        self.assertIn('DownloadReady:false',c)
        self.assertIn('receipt.Status="staged"',c)
        self.assertIn('receipt.Status="bounded_live_staged"',c)
        self.assertIn('receipt.ReadyForMux=!plan.NeedsEmbeddedAudioProof',c)
        self.assertNotIn('DownloadReady=true',c)
        self.assertNotIn('receipt.DownloadReady=true',c)
        self.assertNotRegex(s, r'\b(?:http|https)\s*\.\s*(?:Get|Post|Client|NewRequest)\s*\(')
        self.assertNotRegex(s, r'(?m)^\s*"net/http"\s*$')
        # Secrets and raw signed URLs stay in the private execution inputs;
        # only artifact references and scoped IDs enter the receipt.
        receipt = s.split('type DASHPeriodSessionReceipt struct {',1)[1].split('\n}',1)[0]
        self.assertNotIn('MPDURL',receipt)
        self.assertNotIn('CredentialRef',receipt)
        self.assertNotIn('InitializationURL',receipt)
    def test_durable_init_and_fragment_verification_are_mandatory(self):
        c = compact(SRC.read_text())
        for anchor in ('exec.BindDurableStore(sink)',
                       'exec.executeDASHFragment(ctx, f, req.AttemptGeneration, req.CredentialRef)',
                       'sink.VerifyCommitted(existing)',
                       'sink.VerifyCommitted(rec)',
                       'mp07VerifyInit(sink, inventory, f)',
                       'mp07VerifiedInventory(sink)',
                       'if tr.Role == "audio" && audioSink == nil',
                       'if existing.AttemptGeneration > req.AttemptGeneration',
                       'if !found || sink.VerifyCommitted(rec) != nil'):
            self.assertIn(compact(anchor),c,anchor)
    def test_dash01_through_dash16_are_real_go_tests(self):
        s=TST.read_text()
        for num in range(1,17):
            self.assertRegex(s,rf'func\s+TestMP07DASH{num:02d}\w*\(')
        for marker in ('TestMP07DASH04PeriodGapOverlapRejected',
                       'TestMP07DASH09InitFetchFailureIsPartial',
                       'TestMP07DASH10CorruptPriorReceiptFailsClosed',
                       'TestMP07DASH11BoundedDynamicNeverReady',
                       'TestMP07DASH15MissingAudioSinkFailsBeforeNetwork'):
            self.assertIn(marker,s)
    def test_ci05_targeted_registry_and_existing_gates(self):
        c=POLICY.read_text()
        for anchor in ('MP03_PYTHON', 'MP04_PYTHON','MP05_PYTHON','MP06_PYTHON',
                       'MP07_PYTHON = [',
                       'tests.update(MP07_PYTHON)',
                       'scripts/test_xgo_mp07_source_contract.py',
                       'scripts/test_xgo_mp07_staleness_audit.py',
                       'subprocess.run(["go", "test", "./..."]'):
            self.assertIn(anchor,c,anchor)
        t=(ROOT/'scripts/ci/test_xgo_ci_policy.py').read_text()
        self.assertIn('def test_mp07_go_multi_period_requires_real_go_and_security_contracts',t)
        workflow=(ROOT/'.github/workflows/xgo-targeted.yml').read_text()
        self.assertIn(':app:compileDebugKotlin',workflow)
        self.assertIn('test "$SOURCE" = success',workflow)
        self.assertIn('test "$ANDROID" = success',workflow)

if __name__=='__main__':unittest.main(verbosity=2)
