# MP12 P07 — Physical ARM64 acceptance (source-bound, opt-in)

**PR:** #28, `feature/xgo-mp09-consolidated-recording-20261111`.

## Prepared source and recovery rules

- P07 adds a verified-artifact receiver and independent read-only ADB diagnostic.
- A newly generated debug APK pair is produced **only** through the existing,
  unsigned `.github/workflows/android.yml` workflow-dispatch. The signed release
  job remains tag-gated and unmodified.
- The GitHub run must be the **latest** matching exact-head workflow-dispatch
  for PR #28; an older success never overrides a newer failure. Its `validate`
  job must be green, and exactly one non-expired artifact must be present.
- The artifact ZIP is unpacked into a private, empty directory with an exact
  four-file inventory, no symlinks/paths/duplicates, and bounded size.
- `scripts/mp12_p02_provenance.py audit_arm64_pair()` rechecks every APK hash,
  source receipt, all ARM64 ELF PT_LOAD 16K alignments, libraries, ABI, checksum
  rows and provenance; P07 additionally checks run ID against live GitHub.
- The P07 JSON report is outside the four-file pair. It includes no serial,
  auth token, or user name. Output is private and never overwrites old evidence.
- `preflight` only reads ADB device ABI, SDK, emulator marker and connection.
  **No automatic installation**, implicit root, data wipe or app uninstall.
- `install-and-test` requires both a literal `--ack-install` token and a fresh
  interactive device-write confirmation; then delegates to
  `scripts/run_physical_arm64_instrumentation.sh` without changing it.

## Evidence and blocked gates

A clean `prepare` yields **verified ARM64 build provenance + read-only device
preflight**, not physical instrumentation. A successful opted-in
`install-and-test` yields a real physical device instrumentation receipt,
**not** full media transfer/recovery soak or release approval.

Still blocked: 1DM+ lawful comparison; full Android media transfer and restart
soak; independently signed, tag-gated APK/AAB provenance; x86_64 opt-in real
native runtime; real desktop Firefox end-to-end integration; release gating and
production Go cutover. Existing MP12 P01–P06 contracts remain intact.

Run the 50-case P07 source tests with `python3 -B scripts/test_mp12_p07_device_acceptance.py`.
The inherited MP12 Python source gate must execute this test and the
`source-only` P07 audit on GitHub. Real device writes never run in CI.
