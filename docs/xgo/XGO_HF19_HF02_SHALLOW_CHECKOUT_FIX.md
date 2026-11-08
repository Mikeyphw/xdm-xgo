# XGO HF19 HF02 — Shallow-checkout CI repair

**Observed:** HF19 HF01 at `031a6bcd825f4e23948f84ea06e494c5557759be` triggered Android CI run 42443408992. Its `validate` job failed during the new HF19 source test when `git show ef0892eeca92e469f8170d543fbb295c68f1ecab:.github/workflows/android.yml` could not find the historical object in the GitHub PR checkout. The native build never started; no HF19 APK pair was published.

**Fix:** The test verifies the *entire* signed-release job stanza against a SHA256 checksum pinned from the verified HF18 workflow, rather than requesting historical Git objects. It fails closed on any change to release signing, attestation, device gates or publication. The original release job itself remains unchanged. This fix adds no network access, no `git fetch`, no Gradle on Termux, and no extra workflow trigger.

Baseline signed-release stanza digest (UTF-8; between `\n  signed-release:\n` and `\n  emulator-compatibility:\n`):

`f84b6fe9830f938250e406b62087002558819fc95f333fe04219ae66ca8becd3`

**Source:** PR #1, branch `fix/xgo-android-sdk-action-20261106`, HF19 HF01 `031a6bcd825f4e23948f84ea06e494c5557759be`, tree `df4b7cd7c96759049cf0ac584ca1e64965eb58da`. Only the HF19 source regression test is modified. Native aria2/OpenSSL and FFmpeg logic from HF19 HF01 remains as-is.

**Limitations:** Passing HF19 HF02 will unblock the expensive hosted native build; it will not demonstrate that FFmpeg and aria2 actually pass on an ARM64 phone. Use the new APK pair from the passing run for 26-test ADB qualification. Do not treat a green emulator-compatibility lane as physical ARM64 runtime acceptance.
