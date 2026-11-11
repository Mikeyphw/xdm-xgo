#!/usr/bin/env python3
"""MP01 HF04: deterministic, dependency-free CI tier and metadata source contracts.

Runs in the lightweight GitHub job without Gradle/Android SDK, and in Termux.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/android.yml'
MODERN = ROOT / '.github/workflows/modern-ci.yml'
WEB_VALIDATOR = ROOT / 'app/XDM.Android/tools/validate-live-locator-title-naming.py'
SECURE_TEST = ROOT / 'app/XDM.Android/browser-extension/tests/test_secure_handoff.js'


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError('MP01_HF04_CI_POLICY_REFUSED: ' + message)


def main() -> None:
    wf = WORKFLOW.read_text(encoding='utf-8')
    modern = MODERN.read_text(encoding='utf-8')
    js = SECURE_TEST.read_text(encoding='utf-8')
    validator = WEB_VALIDATOR.read_text(encoding='utf-8')

    check('  pull_request:\n' not in wf, 'full Android workflow still auto-runs on PR')
    check('  pull_request:\n' not in wf and
          'types: [opened, reopened, synchronize, labeled, unlabeled, ready_for_review]' not in wf,
          'full Android workflow still listens to PR labels')
    check("  push:\n    tags: ['android-v*']" in wf and 'branches: [main]' not in wf,
          'Android main auto-build is enabled or release tag gate missing')
    check('  workflow_dispatch:' in wf, 'manual full qualification route removed')
    targeted = (ROOT / ".github/workflows/xgo-targeted.yml").read_text(encoding="utf-8")
    router = (ROOT / ".github/workflows/xgo-full-gate-router.yml").read_text(encoding="utf-8")
    check("  pull_request:" in targeted and "  push:" in targeted, "targeted PR/main checks missing")
    check("  targeted-qualification:" in targeted, "no distinct targeted status")
    check("  full-gate:" in router and "gate-dispatch" in router, "full gate router missing")
    check('  hotfix-fast:\n' in wf, 'fast preflight missing')
    check('  validate:\n    needs: hotfix-fast\n' in wf,
          'heavy validation does not depend on fast preflight')
    check('  android-pr-merge-qualification:\n' in wf, 'fail-closed PR check missing')
    check("if: github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'xdm-full-ci')" in wf,
          'PR full build is not tied to maintainer opt-in label')
    check("if: always() && github.event_name == 'pull_request'" in wf,
          'PR merge qualification can be skipped when heavy builds fail')
    check('needs: [hotfix-fast, validate, emulator-compatibility]' in wf,
          'PR merge approval is not bound to full build AND hosted emulator')
    check('"$FAST_RESULT" != success || "$FULL_RESULT" != success || "$EMULATOR_RESULT" != success' in wf,
          'PR fast-only runs could be falsely approved')

    fast = wf.split('  hotfix-fast:\n',1)[1].split('\n  validate:\n',1)[0]
    heavy = wf.split('  validate:\n',1)[1].split('\n  instrumentation:\n',1)[0]
    check('bash tools/run-final-release-gate.sh --ci' in fast,
          'fast job does not run complete static release gate')
    check('node "browser-extension/tests/$suite"' in fast and 'test_secure_handoff.js' in fast,
          'fast job does not run real encrypted capture JS regression')
    check('test_background.js' in fast and 'test_release_gate.js' in fast,
          'fast job does not exercise background/privacy release tests')
    check('scripts/test_xgo_mp01_hf04_ci_tiers.py' in fast,
          'fast CI tier policy test not executed')
    check('sdkmanager ' not in fast and 'setup-gradle@' not in fast and
          'gradle wrapper' not in fast and 'setup-android@' not in fast,
          'fast job accidentally performs full Android provisioning')
    check('sdkmanager "platforms;android-36"' in heavy and 'gradle/actions/setup-gradle@v6' in heavy and 'gradle/actions/setup-gradle@v4' not in heavy,
          'full Android SDK/Gradle job has been weakened')
    check('bash tools/run-final-common-validation.sh' in heavy,
          'full Android unit/compile/lint/packaging gate removed')
    check('Verify and stage one native ARM64 debug/instrumentation APK pair' in heavy,
          'full Android APK artifact qualification removed')
    check('  emulator-compatibility:\n' in wf and 'run-hosted-emulator-compatibility.sh' in wf,
          'existing hosted emulator qualification removed')
    check('  signed-release:\n' in wf and 'run-hosted-emulator-instrumentation.sh --signed-release' in wf,
          'signed release safety gate removed')

    # Desktop parity: Android-only hotfixes must not keep provisioning Windows
    # ARM64 compilers or building the complete .NET solution until final PR opt-in.
    check('  pull_request:\n' not in modern and '  push:\n' not in modern and '  workflow_dispatch:' in modern,
          'full Modern workflow is not manual-gate only')
    check(wf.count('  android-pr-merge-qualification:') == 1 and
          modern.count('  modern-pr-merge-qualification:') == 1,
          'full qualification jobs must have unique cross-workflow names')
    check('  modern-fast:\n' in modern and '  validate:\n    needs: modern-fast\n' in modern,
          'desktop fast-first gate missing')
    check('  modern-pr-merge-qualification:\n' in modern and
          'needs: [modern-fast, validate, native-linux-arm64, native-windows-arm64]' in modern,
          'modern PR qualification must require all native/full lanes')
    check("needs: modern-fast\n    if: github.event_name != 'pull_request'" in modern,
          'modern full jobs not gated behind fast and PR opt-in')
    check(modern.count("contains(github.event.pull_request.labels.*.name, 'xdm-full-ci')") == 3,
          'all three modern full lanes must require the same opt-in label')
    modern_fast = modern.split('  modern-fast:\n',1)[1].split('\n  validate:\n',1)[0]
    modern_full = modern.split('  validate:\n',1)[1].split('\n  modern-pr-merge-qualification:\n',1)[0]
    check('validate-xfe01-single-firefox-extension.py' in modern_fast and
          'rem18-release-matrix-audit.py' in modern_fast and
          'scripts/test_xgo_mp01_hf04_ci_tiers.py' in modern_fast,
          'desktop fast static source attestations missing')
    check('dotnet ' not in modern_fast and 'setup-dotnet@' not in modern_fast and
          'setup-go@' not in modern_fast and 'LLVM-MinGW' not in modern_fast,
          'modern fast check unexpectedly builds/provisions native toolchains')
    check('dotnet build app/XDM/XDM.Modern.sln' in modern_full and
          'dotnet test app/XDM/XDM.Modern.sln' in modern_full,
          'modern full OS matrix no longer builds/tests')
    check('runs-on: ubuntu-24.04-arm' in modern and 'runs-on: windows-11-vs2026-arm' in modern and
          'Provision SHA-256 pinned Windows ARM64 LLVM-MinGW compiler' in modern,
          'native ARM64 desktop qualification missing')
    check('"$FAST_RESULT" != success || "$MATRIX_RESULT" != success' in modern and
          '"$WINDOWS_ARM64_RESULT" != success' in modern,
          'modern unqualified PR could be incorrectly reported green')

    for needle in ('durationMs:630000', 'thumbnailUrl:"https://img.example/poster.jpg"',
                   'assert.equal(json.candidates[0].durationMs,630000)',
                   'assert.equal(json.candidates[0].thumbnailUrl,"https://img.example/poster.jpg")',
                   'assert(!session.includes("poster.jpg"))',
                   'assert.equal(json.candidates[0].finalHeaders.authorization,"Bearer private")',
                   'webcrypto.subtle.decrypt'):
        check(needle in js, f'encrypted real JS metadata regression missing: {needle}')
    check('secure_handoff_test = read("browser-extension/tests/test_secure_handoff.js")' in validator,
          'WEB01 static gate still reads obsolete public-only JS test')
    check("'batch[1].durationMs,630000'" not in validator,
          'WEB01 static gate still requires plaintext-v3 metadata')
    print('MP01_HF04_CI_TIERS_PASS: Aurora-style targeted PR, manual full Android/Modern jobs, five-integration gate router, encrypted metadata regression')


if __name__ == '__main__':
    main()
