#!/usr/bin/env python3
"""MP11 P04 native Compose test/source contracts and mutation negatives.

This is a *source* audit. Actual Compose instrumentation must run on an API36
emulator through the opt-in workflow; do not claim the parser as UI evidence.
"""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = Path('app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android')
SCREEN = ROOT / APP / 'ui/media/MediaInboxScreen.kt'
LIBRARY = ROOT / APP / 'ui/library/MediaLibraryScreen.kt'
INDEX = ROOT / APP / 'engine/MP11LiveLibraryIndex.kt'
SURFACE = ROOT / APP / 'ui/media/MP11P04UiSurfaces.kt'
DIAGNOSTICS = ROOT / APP / 'engine/MP11P04Diagnostics.kt'
INSTRUMENTED = ROOT / 'app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/MP11P04LiveRecordingUiInstrumentedTest.kt'
DRIVER = ROOT / 'scripts/test_mp11_p04_instrumentation.py'
WORKFLOW = ROOT / '.github/workflows/xgo-mp11-p04-ui.yml'
TEST_NAMES = (
    'recordingActionsRespectDvrAndUnknownState',
    'refreshNeedsAllThreeSameOriginUrlsAndExplicitApprove',
    'destructiveDiscardNeedsSeparateConfirmationAndSupportsKeep',
    'publishingRecoveryNeverOffersResumeOrDestructiveDiscard',
    'onlyVerifiedLiveTileExposesOpenAndDetails',
)
PRODUCTION_LINKS = {
    'MP11P04RecordingControls(': SCREEN,
    'MP11P04DiscardDialog(': SCREEN,
    'MP11P04RefreshDialog(': SCREEN,
    'MP11P04RecoveryDialog(': SCREEN,
    'MP11P04VerifiedLiveTile(': LIBRARY,
    'MP11P04ReviewOnlyRow(': LIBRARY,
}

def require(condition, label):
    if not condition: raise AssertionError('MP11_P04_SOURCE_REFUSED_' + label)

def audit_instrumented(src):
    require('createComposeRule()' in src and 'composeRule.setContent' in src,
            'REAL_COMPOSE_RULE_MISSING')
    for name in TEST_NAMES:
        require(src.count('fun '+name+'(') == 1, 'COMPOSE_TEST_MISSING_'+name)
    require('@Test fun' in src and src.count('@Test fun') == len(TEST_NAMES),
            'WRONG_COMPOSE_TEST_COUNT')
    for token in ('performClick()', 'performTextInput(', 'assertIsNotEnabled()',
                  'assertDoesNotExist()', 'MP11P04Tags.RecoveryResume',
                  'MP11P04Tags.ConfirmDiscard', 'MP11P04Tags.OpenVerified',
                  'MP11P04Tags.ConfirmRefresh',
                  'onNodeWithText("Reauthorize & resume")'):
        require(token in src, 'UI_ACTION_ASSERTION_MISSING')
    require('MP11P04LiveRecordingUiInstrumentedTest' in src,
            'REAL_ANDROID_CLASS_MISSING')

def audit_ui(surfaces,screen,library):
    for token, owner in PRODUCTION_LINKS.items():
        source = screen if owner == SCREEN else library
        require(source.count(token) == 1, 'PRODUCTION_CALL_NOT_UNIQUE_'+token)
        require(surfaces.count('fun '+token) == 1, 'SURFACE_NOT_EXTRACTED_'+token)
    require('Modifier.testTag(MP11P04Tags.Stop)' in surfaces,
            'RECORDING_SEMANTICS_MISSING')
    require('Modifier.testTag(MP11P04Tags.ReviewOnly)' in surfaces,
            'REVIEW_NON_PLAYABLE_SEMANTICS_MISSING')
    require('MP11LiveUiPolicy.actions(state, dvrCapable)' in surfaces,
            'NO_GO_PROJECTION_POLICY')
    require('enabled = MP11LiveUiPolicy.validRefresh(root, video, audio)' in surfaces,
            'REFRESH_CONFIRMATION_NOT_GATED')
    require('if (canResume)' in surfaces and 'if (!publishing' in surfaces,
            'INTERRUPTED_PUBLICATION_NOT_GATED')
    require('MediaRequestHandoffStore.rememberCapture(' in screen and
            'AndroidLiveRecordingService.refreshAuthorized(context, request)' in screen,
            'REFRESH_BYPASSES_EXISTING_AUTHORITY')
    # The MP09 final contract requires this user-visible action to remain
    # anchored to MediaInboxScreen even after P04 extracts the Compose dialog.
    # A dead string/comment is insufficient: ensure the label is passed as an
    # actual argument and rendered by the production recovery button.
    require('resumeLabel = "Reauthorize & resume"' in screen and
            'Text(resumeLabel)' in surfaces,
            'MP09_RECOVERY_ACTION_LABEL_NOT_WIRED')
    require('MP11P04Diagnostics.code(' in screen and 'MP11P04Diagnostics.code(' in library,
            'PRODUCTION_DIAGNOSTICS_NOT_WIRED')

def audit_workflow(workflow, driver):
    for token in ('xgo-mp11-p04-api36', 'pull_request:', 'types: [labeled]',
                  "github.event.pull_request.head.repo.full_name == github.repository",
                  'inputs.run_api36 == true', 'contents: read',
                  'MP11_P04_EXPECTED_SHA', 'test -c /dev/kvm',
                  'python3 -B scripts/test_mp11_p04_instrumentation.py --api36-execute'):
        require(token in workflow, 'HOSTED_EXECUTION_GUARD_MISSING')
    for token in ("'-Pandroid.testInstrumentationRunnerArguments.class=' + CLASS",
                  'verify_receipts(output, started, real_execution=True)', 'MP11_P04_API36_FIVE_REAL_COMPOSE_TESTS_PASS',
                  'MP11_P04_OPTED_IN', 'ro.kernel.qemu', 'ro.build.version.sdk',
                  'MP11_P04_JUNIT_CASE_SET_INCOMPLETE'):
        require(token in driver, 'JUNIT_RECEIPT_GUARD_MISSING')
    require('script: python3 -B scripts/test_mp11_p04_instrumentation.py --api36-execute' in workflow,
            'RUNNER_COMMAND_REQUIRED')
    require('createComposeRule' not in driver, 'SYNTHETIC_COMPOSE_PASS')

def audit_index(src):
    require('if (!published.exists()) {' in src and
        'return MP11LiveLibrarySnapshot(review = review)' in src,
        'NO_RECEIPT_RECOVERY_INVISIBLE')
    require('if (item == null) review +=' in src and
        'MP11P04Diagnostics.Area.Library' in src,
        'LIBRARY_READBACK_DIAGNOSTIC_MISSING')

def audit_diagnostics(src):
    require('enum class Area' in src and 'enum class Outcome' in src,
            'CLOSED_DIAGNOSTIC_TAXONOMY_MISSING')
    require('fun stateLabel(raw: String?)' in src and
            'else -> "Review required"' in src,
            'UNTRUSTED_GO_STATE_EXPOSED')
    for forbidden in ('android.util.Log', 'Log.d(', 'println(', 'Throwable.message',
                      'captureId:', 'sourceUrl:', 'token:', 'cookie:'):
        require(forbidden not in src, 'POTENTIAL_SECRET_IN_DIAGNOSTIC')

def check_full():
    for file in (SCREEN, LIBRARY, INDEX, SURFACE, DIAGNOSTICS, INSTRUMENTED,
                 DRIVER, WORKFLOW): require(file.is_file(), 'FILE_MISSING_'+file.name)
    surface = SURFACE.read_text()
    screen = SCREEN.read_text()
    lib = LIBRARY.read_text()
    audit_ui(surface,screen,lib)
    audit_index(INDEX.read_text())
    audit_diagnostics(DIAGNOSTICS.read_text())
    audit_instrumented(INSTRUMENTED.read_text())
    audit_workflow(WORKFLOW.read_text(),DRIVER.read_text())

class SourceContracts(unittest.TestCase):
    def test_exact_source(self):
        check_full()
    def test_injected_mutation_negatives(self):
        ui= SURFACE.read_text()
        screen=SCREEN.read_text()
        library=LIBRARY.read_text()
        cases=[
            lambda: audit_ui(ui.replace('MP11LiveUiPolicy.actions(state, dvrCapable)', 'setOf("pause")'), screen, library),
            lambda: audit_ui(ui.replace('enabled = MP11LiveUiPolicy.validRefresh(root, video, audio)', 'enabled = true'), screen, library),
            lambda: audit_ui(ui, screen.replace('MP11P04RefreshDialog(', 'FakeRefreshDialog('), library),
            lambda: audit_ui(ui, screen.replace('resumeLabel = "Reauthorize & resume"', 'resumeLabel = "Resume"'), library),
            lambda: audit_ui(ui.replace('Text(resumeLabel)', 'Text("Resume")'), screen, library),
            lambda: audit_ui(ui, screen.replace('MediaRequestHandoffStore.rememberCapture(', 'false('), library),
            lambda: audit_ui(ui, screen, library.replace('MP11P04VerifiedLiveTile(', 'UnsafeFileTile(')),
            lambda: audit_instrumented(INSTRUMENTED.read_text().replace('performTextInput(', 'nonInteracting(')),
            lambda: audit_workflow(WORKFLOW.read_text().replace('test -c /dev/kvm', 'true'), DRIVER.read_text()),
            lambda: audit_workflow(WORKFLOW.read_text(), DRIVER.read_text().replace('verify_receipts(output, started, real_execution=True)', 'pass')),
            lambda: audit_index(INDEX.read_text().replace('return MP11LiveLibrarySnapshot(review = review)', 'return MP11LiveLibrarySnapshot()')),
            lambda: audit_diagnostics(DIAGNOSTICS.read_text().replace('else -> "Review required"', 'else -> raw.orEmpty()')),
        ]
        for i,case in enumerate(cases):
            with self.subTest(case=i):
                with self.assertRaises(AssertionError): case()

if __name__ == '__main__':
    unittest.main(verbosity=2)
