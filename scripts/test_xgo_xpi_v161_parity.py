#!/usr/bin/env python3
"""XP01: exact authored source parity and generated debug contract from user XPI.

Runs offline and does not depend on Git history, network, Android SDK or device.
"""
import hashlib, json, pathlib, re, subprocess, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
MODULE=ROOT/'app/XDM.Android/browser-extension'
SRC=MODULE/'src/main/extension/xdm-firefox'
MANIFEST=ROOT/'docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'
VERSION='1.6.1'
SIGNED_RELEASE_SHA='f84b6fe9830f938250e406b62087002558819fc95f333fe04219ae66ca8becd3'

def sha(blob):return hashlib.sha256(blob).hexdigest()
def release_block(w):
    if w.count('\n  signed-release:\n')!=1 or w.count('\n  emulator-compatibility:\n')!=1:
        raise AssertionError('signed release boundary missing or duplicated')
    return w.split('\n  signed-release:\n',1)[1].split('\n  emulator-compatibility:\n',1)[0]

class XpiReferenceParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.ref=json.loads(MANIFEST.read_text(encoding='utf-8'))
    def test_exact_seven_authored_assets_and_six_retained_assets(self):
        self.assertEqual(len(self.ref['adoptedAssetSha256']),7)
        self.assertEqual(len(self.ref['unchangedAssetSha256']),6)
        for group in ['adoptedAssetSha256','unchangedAssetSha256']:
            for name,digest in self.ref[group].items():
                self.assertEqual(sha((SRC/name).read_bytes()),digest,name)
    def test_mp01_encrypted_canonical_and_reference_snapshot_are_distinct(self):
        # Preserve the user-supplied XP01 provenance while attesting the CURRENT
        # Android-owned canonical XPI. Signed/credential-bearing captures must
        # not regress to the historical, plaintext-v3 reference artifact.
        historical=self.ref['referenceSnapshotBeforeMp01Sha256']
        self.assertEqual(historical['handoff.js'], '19dd11fba950c20725b6860ed5def908f4e38da7fb179cb458ad70ca066572a2')
        self.assertEqual(historical['network-observer.js'], '7988d45e1810f750adbe2f5443143cbe0f43ec9d826a4b2b16a6f67611224274')
        self.assertEqual(historical['generated-config.js'], 'e7c0adc1cf7e6e33e3f6ca6ed72008d83ea1b79923e98fed63681a1c7a02ccff')
        self.assertNotEqual(historical['handoff.js'], self.ref['adoptedAssetSha256']['handoff.js'])
        handoff=(SRC/'handoff.js').read_text(encoding='utf-8')
        for marker in ('async function buildCaptureSession(', 'const pairing = pairedCaptureConfig()',
                       'const uri = `${scheme}://capture?v=2&sid=', 'subtle.encrypt({ name: "AES-GCM"',
                       'subtle.encrypt({ name: "RSA-OAEP"', 'if (hasCredentialHeader(input)) return ""'):
            self.assertIn(marker,handoff)
        for forbidden in ('params.set("headers"', 'params.set("finalHeaders"', 'params.set("proposedHeaders"'):
            self.assertNotIn(forbidden,handoff)
        encrypted=(MODULE/'tests/test_secure_handoff.js').read_text(encoding='utf-8')
        for marker in ('json.candidates[0].durationMs,630000',
                       'json.candidates[0].thumbnailUrl,"https://img.example/poster.jpg"',
                       'json.candidates[0].finalHeaders.authorization,"Bearer private"',
                       'webcrypto.subtle.decrypt'):
            self.assertIn(marker,encrypted)

    def test_version_channel_and_manifest_restrictions(self):
        build=(MODULE/'build.gradle.kts').read_text()
        contract=(MODULE/'src/main/kotlin/com/mikeyphw/xdm/android/browserextension/BrowserExtensionSourceContract.kt').read_text()
        prepare=(MODULE/'tools/prepare_extension.py').read_text()
        self.assertIn('val extensionVersion = "'+VERSION+'"',build)
        self.assertIn('"--application-id", "com.mikeyphw.xdm.android.debug"',build)
        self.assertIn('"--xdm-scheme", "xdmdownload-debug"',build)
        self.assertIn('"--default-target", "xdm"',build)
        self.assertIn('const val DevelopmentVersion = "'+VERSION+'"',contract)
        self.assertIn('parser.add_argument("--extension-version", default="'+VERSION+'")',prepare)
        self.assertIn('"version": "@@EXTENSION_VERSION@@"',(SRC/'manifest.template.json').read_text())
        self.assertIn('"data_collection_permissions"',(SRC/'manifest.template.json').read_text())
        self.assertNotIn('capturePublicKeySpki',(SRC/'generated-config.template.js').read_text())
    def test_normalized_reference_debug_render(self):
        with tempfile.TemporaryDirectory() as td:
            result=subprocess.run([sys.executable,str(MODULE/'tools/prepare_extension.py'),
              '--source',str(SRC),'--output',td,
              '--extension-version',VERSION,'--app-version','0.21.0-debug',
              '--application-id','com.mikeyphw.xdm.android.debug','--channel','debug',
              '--xdm-scheme','xdmdownload-debug','--default-target','xdm','--theme','dark'],
              capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+' '+result.stderr)
            out=pathlib.Path(td)
            manifest=json.loads((out/'manifest.json').read_text())
            self.assertEqual(manifest['version'],VERSION)
            self.assertEqual(manifest['browser_specific_settings']['gecko']['id'],'xdm-android-media-bridge@mikeyphw')
            self.assertEqual(set(manifest['permissions']),{'storage','tabs','activeTab','webRequest','<all_urls>'})
            self.assertEqual(manifest['browser_specific_settings']['gecko']['data_collection_permissions']['required'],['none'])
            config=(out/'generated-config.js').read_text()
            self.assertIn('extensionVersion: "'+VERSION+'"',config)
            self.assertIn('applicationId: "com.mikeyphw.xdm.android.debug"',config)
            self.assertIn('xdmScheme: "xdmdownload-debug"',config)
            self.assertIn('contractVersion: 3',config)
            self.assertIn('defaultTarget: "xdm"',config)
            self.assertIn('--xdm-theme-mode: dark',(out/'generated-theme.css').read_text())
            for name,digest in self.ref['normalizedGeneratedSha256'].items():
                self.assertEqual(sha((out/name).read_bytes()),digest,'normalized generated '+name)
            for p in sorted(self.ref['adoptedAssetSha256']):
                self.assertEqual(sha((out/p).read_bytes()),self.ref['adoptedAssetSha256'][p],p)
            for p in self.ref['unchangedAssetSha256']:
                self.assertEqual(sha((out/p).read_bytes()),self.ref['unchangedAssetSha256'][p],p)
            # Validate the complete rendered extension with pre-existing repository check.
            check=subprocess.run([sys.executable,str(MODULE/'tools/validate_extension.py'),str(out)],capture_output=True,text=True)
            self.assertEqual(check.returncode,0,check.stdout+' '+check.stderr)
    def test_browser_selected_media_ui_and_evidence_boundary(self):
        popup=(SRC/'popup.html').read_text()
        js=(SRC/'popup.js').read_text()
        background=(SRC/'network-observer.js').read_text()
        fab=(SRC/'fab.js').read_text()
        for needle in ['sendSelectedMedia','sendSelectedMedia1Dm','logicalMediaCandidates','role="radiogroup"']:
            self.assertIn(needle,popup)
        for needle in ['xdmGetLogicalCandidatesV2','xdmSendLogicalCandidatesV2','xdmSendLogicalCandidatesTo1DmV1']:
            self.assertIn(needle,js+background)
        for needle in ['requireSingleSelectedCandidate','findPrivilegedEvidence','browser.webRequest.onBeforeSendHeaders','sendLogicalCandidates']:
            self.assertIn(needle,background)
        self.assertIn('pickerRequired',fab)
        self.assertIn('xdm-picker',fab)
        self.assertIn('showPossibleMediaCandidates',background)
    def test_retained_phase38_gate_uses_explicit_1dm_intent_target(self):
        gate=(ROOT/'app/XDM.Android/tools/validate-phase-38-repo-owned-extension.py').read_text()
        self.assertIn("'scheme=idmdownload'",gate)
        self.assertIn("'package=idm.internet.download.manager.plus'",gate)
        self.assertNotIn("'sanitizeHeaderBag', 'idmdownload:'",gate)
        handoff=(SRC/'handoff.js').read_text()
        self.assertIn('scheme=idmdownload',handoff)
        self.assertIn('package=idm.internet.download.manager.plus',handoff)
        self.assertIn('return ""',handoff)

    def test_xar10_source_gate_matches_v161_closed_shadow_and_one_selected_media(self):
        # XAR10 must test executable code instead of historical explanatory strings.
        gate=(ROOT/'app/XDM.Android/tools/validate-xar10-browser-capture-evidence.py').read_text()
        fab=(SRC/'fab.js').read_text()
        network=(SRC/'network-observer.js').read_text()
        for expected in [
            'shadow = host.attachShadow({ mode: "closed" });',
            'host.dataset.candidateCount = String(current.candidateCount);',
        ]:
            self.assertIn(expected,gate)
            self.assertIn(expected,fab)
        for expected in [
            'function requireSingleSelectedCandidate',
            'const candidate = Object.assign({}, selected, {',
            'streamKind: candidateStreamKind(selected),',
            'browserHandoff: Object.assign({}, selected.browserHandoff || {}, {',
            'finalHeaders: authoritative ? proof.browserHandoff.finalHeaders : null,',
            'headers: authoritative ? proof.headers : {},',
            'await handoff.buildCaptureSession({',
            'candidates: [candidate]',
            'totalCandidateCount: 1',
            'truncated: false',
        ]:
            self.assertIn(expected,gate)
            self.assertIn(expected,network)
        self.assertNotIn('closed Shadow DOM keeps privileged XDM capture URLs',gate)
        self.assertNotIn('refusing to drop selected variants/tracks',gate)
        self.assertNotIn('attachShadow({ mode: "open" })',fab)
        result=subprocess.run([
            sys.executable,'-B',str(ROOT/'app/XDM.Android/tools/validate-xar10-browser-capture-evidence.py')
        ],cwd=ROOT/'app/XDM.Android',capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
    def test_xfe01_desktop_canonical_baseline_matches_current_xpi(self):
        source=ROOT/'app/XDM/eng/validate-xfe01-single-firefox-extension.py'
        self.assertTrue(source.is_file())
        code=source.read_text()
        # All 16 XFE01 baselines must match the canonical on-disk source, not only the seven imported assets.
        desktop_hashes=dict(re.findall(r'^[ ]+"([^"]+)": "([0-9a-f]{64})",?$',code,re.M))
        self.assertEqual(len(desktop_hashes),16)
        for asset,digest in desktop_hashes.items():
            data=(SRC/asset).read_bytes()
            if asset.endswith(('.js','.css','.html','.json')):
                self.assertNotIn(bytes((13,)),data.replace(bytes((13,10)),b''))
                data=data.replace(bytes((13,10)),bytes((10,)))
            self.assertEqual(sha(data),digest,asset)
        reference=self.ref['adoptedAssetSha256']
        for asset,digest in reference.items():
            self.assertIn('"'+asset+'": "'+digest+'"',code)
        result=subprocess.run([
            sys.executable,'-B',str(source)
        ],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


    def test_runtime_foundation_gate_enforces_v161_one_selected_item(self):
        gate=(ROOT/'app/XDM.Android/tools/validate-runtime-foundation-phase59-61.py').read_text()
        network=(SRC/'network-observer.js').read_text()
        fab=(SRC/'fab.js').read_text()
        for needle in [
            'const chooserRequired = true;',
            'const prebuiltXdmLink = "";',
            'const prebuiltOneDmLink = "";',
            'const capturedCandidateCount = 0;',
            'function requireSingleSelectedCandidate(tabId, requestedIds, targetLabel)',
            'if (ids.length !== 1)',
            'if (selected.length !== 1)',
            'candidates: [candidate]',
            'totalCandidateCount: 1',
            'truncated: false',
        ]:
            self.assertIn(needle,gate)
            self.assertIn(needle,network)
        self.assertNotIn('visibleCandidates.slice(0, MAX_HANDOFF_CANDIDATES)',network)
        self.assertIn('retired multi-candidate automatic handoff',gate)
        self.assertIn('shadow = host.attachShadow({ mode: "closed" });',fab)
        fab_test=(MODULE/'tests/test_fab.js').read_text()
        background_test=(MODULE/'tests/test_background.js').read_text()
        frame_test=(MODULE/'tests/test_phase43a_bridge.js').read_text()
        self.assertIn('single-choice picker tests passed',fab_test)
        self.assertIn('network detection must not build an unselected capture session',background_test)
        self.assertIn('Multi-select must be rejected',background_test)
        self.assertIn('pickerRequired: true',frame_test)
        result=subprocess.run([sys.executable,'-B',str(ROOT/'app/XDM.Android/tools/validate-runtime-foundation-phase59-61.py')],cwd=ROOT/'app/XDM.Android',capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+"\n"+result.stderr)

    def test_retained_parity02_and_phase43a_seals_match_v161_picker(self):
        parity=(ROOT/'app/XDM.Android/tools/validate-media-parity02-logical-capture.py').read_text()
        phase=(ROOT/'app/XDM.Android/tools/validate-phase-43a-browser-extension-parity.py').read_text()
        popup=(SRC/'popup.js').read_text()
        network=(SRC/'network-observer.js').read_text()
        fab=(SRC/'fab.js').read_text()
        manifest=json.loads((SRC/'manifest.template.json').read_text())
        self.assertNotIn("'Send ${count} to XDM' in popup",parity)
        for marker in ('async function sendSelectedLogicalCandidate(target)',
                       'logicalMediaIds: [id]', 'sendSelectedLogicalCandidatesToOneDm'):
            self.assertIn(marker,popup)
            self.assertIn(marker,parity)
        for marker in ('if (ids.length !== 1)','candidates: [candidate]',
                       'const chooserRequired = true;', 'const prebuiltXdmLink = "";'):
            self.assertIn(marker,network)
            self.assertIn(marker,parity)
        self.assertIn('shadow = host.attachShadow({ mode: "closed" });',fab)
        self.assertIn('1.6.1',phase)
        self.assertIn('"handoff.js",\n    "network-observer.js",',phase)
        self.assertEqual(manifest['background']['scripts'],
            ['generated-config.js','detector-core.js','candidate-store.js','handoff.js','network-observer.js'])
        verifier=(MODULE/'tools/verify_release_artifacts.py').read_text()
        devtool=(ROOT/'.devtool.toml').read_text()
        gradle=(MODULE/'build.gradle.kts').read_text()
        project=json.loads((ROOT/'app/XDM.Android/PROJECT_MANIFEST.json').read_text())
        self.assertIn(r'REQUIRED_FILES={',verifier)
        self.assertIn('"bridge-selftest.js"',verifier)
        self.assertIn(r'REQUIRED_FILES\s*=',phase)
        for task in ('":browser-extension:jsTest"',
                     '":browser-extension:test"',
                     '":browser-extension:validateFirefoxExtension"'):
            self.assertIn(task,devtool)
            self.assertIn(task,phase)
        self.assertIn('dependsOn(verifyFirefoxExtensionReleaseArtifacts)',gradle)
        self.assertIn('dependsOn(verifyFirefoxExtensionReleaseArtifacts)',phase)
        self.assertEqual(project['next_phase'],'XAR17_313_root_closure_audit_final_gate')
        self.assertIn('"XAR17_313_root_closure_audit_final_gate"',phase)
        for gate in ('validate-media-parity02-logical-capture.py',
                     'validate-phase-43a-browser-extension-parity.py'):
            result=subprocess.run([sys.executable,'-B',str(ROOT/'app/XDM.Android/tools'/gate)],
                cwd=ROOT/'app/XDM.Android',capture_output=True,text=True)
            self.assertEqual(result.returncode,0,gate+'\n'+result.stdout+'\n'+result.stderr)

    def test_kotlin_phase59_parity02_gate_matches_v161_explicit_single_selection(self):
        browser=(ROOT/'app/XDM.Android/app/src/test/kotlin/com/mikeyphw/xdm/android/BrowserCapturePhases59_61ContractTest.kt').read_text()
        parity=(ROOT/'app/XDM.Android/app/src/test/kotlin/com/mikeyphw/xdm/android/MediaParity02LogicalMediaCaptureContractTest.kt').read_text()
        network=(SRC/'network-observer.js').read_text()
        popup=(SRC/'popup.js').read_text()
        for needle in (
            'function requireSingleSelectedCandidate(tabId, requestedIds, targetLabel)',
            'if (ids.length !== 1)', 'if (selected.length !== 1)',
            'const chooserRequired = true;', 'candidates: [candidate]',
            'totalCandidateCount: 1', 'truncated: false',
            'const capturedCandidateCount = 0;',
        ):
            self.assertIn(needle, network)
            self.assertIn(needle, browser)
        self.assertNotIn('visibleCandidates.slice(0, MAX_HANDOFF_CANDIDATES)', network)
        self.assertIn('assertFalse(network.contains("visibleCandidates.slice(0, MAX_HANDOFF_CANDIDATES)"', browser)
        self.assertNotIn('assertTrue(network.contains("visibleCandidates.slice(0, MAX_HANDOFF_CANDIDATES)"', browser)
        self.assertNotIn('capturedCandidateCount = Math.max(0', browser)
        for needle in ('async function sendSelectedLogicalCandidate(target)',
                       'const id = selectedLogicalId();', 'logicalMediaIds: [id]',
                       'sendSelectedLogicalCandidatesToOneDm'):
            self.assertIn(needle, popup)
            self.assertIn(needle, parity)
        self.assertNotIn('Send ${count} to XDM', popup)
        self.assertIn('assertFalse(popup.contains(', parity)

    def test_release_boundary_is_unchanged(self):
        w=(ROOT/'.github/workflows/android.yml').read_text()
        self.assertEqual(sha(release_block(w).encode()),SIGNED_RELEASE_SHA)
        self.assertEqual(w.count('XP01 XPI v1.6.1 authored parity gate'),1)
        self.assertIn('scripts/test_xgo_xpi_v161_parity.py',w)
        self.assertIn('XDM_XAR16_FULL_RELEASE_GATE',w)

if __name__=='__main__':unittest.main(verbosity=2)
