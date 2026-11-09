# MP01 HF05 — Canonical XPI parity and CI preflight repair

Source-pinned for `Mikeyphw/xdm-xgo` PR #10 at `aff93fb46b123eabe21bf2af41f5b20464f733de`.

## Verified blocker

The first opted-in full Android CI (`42650829192`) passed the static contracts and then failed at `scripts/test_xgo_xpi_v161_parity.py` with four assertions:

- Historical user-XPI `handoff.js` SHA-256 (`19dd11...`) versus current Android canonical encrypted-v2 implementation (`23b649...`).
- Historical `generated-config.js` normalized digest (`e7c0ad...`) versus current unpaired debug renderer (`010c84...`).
- An obsolete one-line `Object.assign` candidate builder assertion; current single-selection, 45-second, exact-request evidence is deliberately split into a guarded, multi-line builder.
- The XP01 test's historical source hash does not match the already updated XFE01 desktop canonical source baseline.

## Changes

1. Reconcile `docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json` active canonical source digests (`handoff.js`, `network-observer.js`) and generated debug-config digest; **preserve historical user-upload digests** under `referenceSnapshotBeforeMp01Sha256`. Does not claim the historical XPI upload itself changed.
2. Improve XP01 source parity tests to require request/frame/generation authorized evidence, candidate metadata inside ciphertext, encrypted v2, and rejection of credential-bearing public Add handoffs.
3. Strengthen XAR10 Python static checks to match the real multi-line candidate builder and verify its exact-request-scope/final-header authority.
4. Run full XP01 Python parity tests and a new HF05 cross-contract guard in `hotfix-fast` before any SDK/NDK/Gradle or emulator, including the nested XFE01 desktop parity audit.
5. Keep full Android CI and emulator **opt-in** through the existing `xdm-full-ci` label. The recovery installer removes this label before pushing, so subsequent hotfixes do not repeatedly launch full CI; add the label again for final qualification.

## Explicit non-goals and boundaries

- Do not modify browser XPI runtime JavaScript, Android cryptography, encryption or native download implementation.
- Do not substitute golden-hash edits for behavior checks: the current canonical handoff, desktop XFE01 map, current test vectors, and generated debug config must all agree on specific SHA-256 digests. Source is pinned by Git blob SHA-1 as well as current PR head.
- Do not weaken or mark success for skipped full-build, Android API36 emulator, signed release, or native Windows/Linux ARM64 gates.
- Local Gradle is never executed. The ZIP is verified locally; hosted full tests remain pending until a final `xdm-full-ci` run.
- The only temporary directories used by the Termux workflow are descendants of `$TMPDIR`.

## Auto PR CI monitoring extension (HF05 WATCH01)

The delivery installer automatically monitors PR #10 at the exact pushed commit. It waits for Android `hotfix-fast`, Modern `modern-fast`, and the MP00 parity workflow to finish, while recognizing that both `*-pr-merge-qualification` jobs intentionally fail in fast-only mode. A real job failure prints the run URL and failed-log tail, and leaves the successfully pushed commit untouched.

- Automatic by default; `XDM_PR_WATCH=0` disables only the watcher.
- For an already-pushed HF05 commit the installer can re-watch idempotently without rewriting the repository.
- `WATCH_PR_CI.py --mode auto` detects the `xdm-full-ci` label: full mode requires Android Gradle and emulator + Modern Linux/Windows and ARM64 + MP00 success at this exact PR SHA.
- No force-push, local Gradle, privileged write, or persistent temp directory. `$TMPDIR` is used by the wrapper and overlay builder.
- Validated with offline mocked GitHub responses, pass/fail/skip matrix tests, SHA drift tests, source script ordering, original HF05 offline overlay tests, and tamper verification. Hosted results after apply remain pending.
