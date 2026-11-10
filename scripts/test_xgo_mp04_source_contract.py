#!/usr/bin/env python3
"""MP04 source/negative-contract audit. Existing selectors and tests remain real."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
E='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/'

def read(rel):return (ROOT/rel).read_text(encoding='utf8')
def check_contract(go,runtime,client,protocol,ui,policy,kt):
    required_go=('func SelectManifestGraph(', 'ManifestRequiredStreamsV1','func ManifestGraphRevision(',
                 'VerifyEmbeddedAudio','VerifyEveryPeriod','ErrManifestSelection','manifestContainerCompatible',
                 'audioGroup','subsGroup','g.Protected','ExecutionReady:false','plan')
    for t in required_go[:-1]:
        if t not in go:raise ValueError('missing Go required-output contract '+t)
    required_runtime=('input.ExpectedRevision != revision','manifest_changed_refresh_required',
                      'input.Selection != nil','selection_incompatible_or_stale','manifest_selection_plan',
                      'media.SelectManifestGraph(', 'media.ResolveManifestGraph(', '"manifest_graph": graph')
    for t in required_runtime:
        if t not in runtime:raise ValueError('runtime bypasses Go authority '+t)
    required_ui=('Mp03ManifestReviewDialog(', 'onVerify = {','manifestChoice = next',
                 'manifestSelectionPlan = null','goManifestClient.resolveManifest(captureId, manifestChoice, revision)',
                 'plan.required.audio','plan.required.subtitle','Plan only — not queued')
    for t in required_ui:
        if t not in ui:raise ValueError('UI not wired end-to-end '+t)
    required_client=('ManifestSelectionV1Contract.Request? = null', 'expectedRevision: String? = null', 'AndroidMediaUiWire.resolvePayload(requestId, captureId, selection, expectedRevision)')
    for t in required_client:
        if t not in client:raise ValueError('client ignored selection '+t)
    required_protocol=('selection.wire()','expected_revision','manifestSelectionPlan = payload.optJSONObject(', 'ManifestSelectionV1Contract::decode')
    for t in required_protocol:
        if t not in protocol:raise ValueError('protocol lost plan '+t)
    for t in ('require(!ready','planned_unverified','MAX','Regex(')[:2]:
        if t not in kt:raise ValueError('Android plan decoder must reject execution ready')
    for t in ('MP04_PYTHON','tests.update(MP04_PYTHON)'):
        if t not in policy:raise ValueError('CI05 missing MP04 contracts')
    return True
class MP04Audit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts=[read('engine/media/manifest_selection.go'),read('engine/runtime/android_manifest_resolve.go'),
          read(E+'AndroidMediaUiClient.kt'),read(E+'AndroidMediaUiProtocol.kt'),
          read('app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/ui/media/MediaInboxScreen.kt'),
          read('scripts/ci/xgo_ci_policy.py'),read(E+'ManifestSelectionV1Contract.kt')]
    def test_required_end_to_end_wiring(self):
        self.assertTrue(check_contract(*self.parts))
    def test_negative_removed_required_audio(self):
        p=list(self.parts);p[0]=p[0].replace('VerifyEmbeddedAudio','BypassAudio')
        with self.assertRaisesRegex(ValueError,'required-output'):check_contract(*p)
    def test_negative_disabled_stale_revision_check(self):
        p=list(self.parts);p[1]=p[1].replace('input.ExpectedRevision != revision','false')
        with self.assertRaisesRegex(ValueError,'authority'):check_contract(*p)
    def test_negative_ui_does_not_reuse_old_plan(self):
        p=list(self.parts);p[4]=p[4].replace('manifestSelectionPlan = null','manifestSelectionPlan = manifestSelectionPlan')
        with self.assertRaisesRegex(ValueError,'UI'):check_contract(*p)
    def test_exact_behavioral_fixtures_present(self):
        tests=read('engine/media/manifest_selection_test.go')
        for t in ('SEL01','SEL02','SEL03','SEL04','SEL05','SEL06','SEL07','SEL08','MUX01','RevisionRejectsMutation'):
            self.assertIn('TestMP04'+t if t!='RevisionRejectsMutation' else 'TestMP04RevisionRejectsMutation',tests)
        self.assertIn('errors.Is(err,ErrManifestSelection)',tests)
    def test_legacy_hls_pipeline_present(self):
        self.assertIn('executeSegment',read('engine/media/hls_execution.go'))
        self.assertIn('NativeHls',read('app/XDM.Android/media/src/main/kotlin/com/mikeyphw/xdm/android/media/MediaDownloadPlanner.kt'))
if __name__=='__main__':unittest.main(verbosity=2)
