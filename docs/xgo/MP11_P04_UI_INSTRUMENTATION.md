# MP11 P04 — Real Compose controls, private diagnostics and opt-in API36 gate

Baseline: PR #28 `4d26b92facccec36f359cecb0101d3639c0d30cf`.

## Production integration

The Media Inbox now uses `MP11P04RecordingControls`,
`MP11P04RefreshDialog`, `MP11P04DiscardDialog` and
`MP11P04RecoveryDialog` directly. Library uses `MP11P04VerifiedLiveTile`
and `MP11P04ReviewOnlyRow`. Their stable test tags are defined in
`MP11P04Tags` inside the production UI source; tests do not duplicate a
mock layout. Unrecognized Go session states show review-only controls.

No composable changes Go/MP05/MP08 ownership of recording, authorized
refresh, fragment deletion, publication, or MediaStore readback.
The three signed refresh URLs remain transient Compose values and are
submitted through the existing encrypted handoff after explicit approval.

The `MP11P04Diagnostics` taxonomy exposes only bounded static codes and
allowlisted Go status labels. Capture IDs, source URLs, cookies, headers,
exception text, file paths and MediaStore URIs are not included in codes.

The P03 library scanner is also hardened: a missing MP08 published-receipt
directory no longer hides an MP09 recording/publishing/published session
from the read-only recovery view. It does **not** promote any item to
playable or downloaded without MP08+MP09 byte/session verification.

## Five real UI tests on API36 (all required)

1. Recording controls: Stop & Save, DVR-only Pause/Resume, unknown-state refusal.
2. Refresh: three URLs and same-origin preflight; no button activation until valid.
3. Discard: no deletion request without distinct confirmation.
4. Recovery: interrupted publishing cannot offer resume or destructive discard.
5. Library: verified tile has Open/Details; review-only item never gets playback actions.

`app/src/androidTest/.../MP11P04LiveRecordingUiInstrumentedTest.kt` executes
against production composables via the Android Compose rule. The driver
`scripts/test_mp11_p04_instrumentation.py --api36-execute` requires exactly
one real Android 36 x86_64 emulator and checks fresh JUnit XML for exactly
those five passing methods. No skipped tests or synthetic receipts count.

## CI qualification boundary

On every PR push, existing XGO Targeted CI and MP08B3 Acceptance compile
Android Kotlin/instrumentation and run normal source/Go/media contracts.
**Compilation is not execution** of the P04 Compose tests.

The new `XGO MP11 P04 API36 Compose UI Acceptance` is opt-in only:
add the `xgo-mp11-p04-api36` label to a same-repo PR or dispatch the
workflow explicitly against exact branch HEAD with `run_api36=true`.
Its result is separate from the default workflows. Neither a skipped gate
nor an x86_64 pass qualifies physical ARM64, extended real recording,
production refresh or release. It also does not bypass UI/device consent.

## Local Devtool overlay safeguards

Use `python3 overlay.zip self-test|doctor|audit-only|apply-and-watch`
from Termux. It pins the exact PR branch, expected SHA and modified blob
hashes; stages changes in a disposable detached worktree; runs inherited
Go/media/runtime and all required Python source contracts; enforces
manifest/inventory, branch safety and non-force push; then watches exact
hosted runs. **Never run Gradle in Termux.** No auto-merge, force push,
rebase, reset or release.

## HF01 inherited MP09 label acceptance
The actual production recovery dialog receives the exact user-facing
`resumeLabel = "Reauthorize & resume"` from Media Inbox. The extracted
composable renders `Text(resumeLabel)`; when Go/MP09 reports an interrupted
publishing phase it still hides this action. The older MP09 source contract
is deliberately **not** modified; P04 contract tests inject label mutations
and require the original wiring to stay intact.
