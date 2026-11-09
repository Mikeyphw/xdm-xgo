# MP01 HF06 — Android JVM phase59-61 and app-paired XPI export

Root failure: [XDM Android CI run 42658756002](https://github.com/Mikeyphw/xdm-xgo/actions/runs/42658756002), `Post-DL03 final common validation`, `:app:testDebugUnitTest` — **485 tests, 3 failed**, all in `BrowserCapturePhases59_61ContractTest.kt`. These tests asserted that current Firefox capture uses plaintext `v3` and a keyless generated XPI, whereas MP01's current secure transport is AES-GCM/RSA-OAEP encrypted `v2`. Source-pinned base: `7e716734225d585577849a15d43450422a4ff1bd`.

## Repair scope

1. Update the three obsolete JVM source contracts to test paired encrypted-v2, rejection of plaintext-v3 navigation, exact-request header authority, one explicit chosen media item, bounded ciphertext, no plaintext credential downgrade, and decrypted artwork/duration security regression evidence. Retain the first, independent non-secret media session test.
2. Repair the real Android XPI export gap: pass `BrowserCaptureEnvelopeManager`'s `keyId`, `publicKeySpkiBase64Url`, and `captureOaepHash` into the existing `BrowserExtensionBuildConfig`. The private RSA key remains in AndroidKeyStore. A failure to obtain key material is reported as failed export instead of silently producing a keyless extension. The optional keyless template remains available for public-only fallback and non-app packaging, not for app-generated secured XPIs.
3. Add `scripts/test_xgo_mp01_hf06_capture_contract.py` to Android `hotfix-fast`, including negative tests to detect missing pairing, plaintext navigation, and unscoped header replay. It runs without Android SDK/NDK/Gradle and does not bypass the `xdm-full-ci` merge gate.

## Release acceptance truth

- Fast Python, XP01, XAR10, XFE01, and Firefox Node tests: may be checked locally/hosted without Gradle.
- The actual Android JVM suite and the API36 emulator **must pass on GitHub Actions before merging**.
- A restored/rotated AndroidKeyStore pairing identity requires generating and installing a new app-paired XPI; standalone keyless extension builds are deliberately limited to public-only URL Add flow. This patch does not purport to implement automatic re-export on key rotation.
- No local Gradle. Temporary extraction, overlays, logs and watcher work use `$TMPDIR`. Devtool source changes are committed in the selected repository only.
