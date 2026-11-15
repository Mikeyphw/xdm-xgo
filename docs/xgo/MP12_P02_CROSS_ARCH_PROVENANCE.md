# MP12 P02 — independent cross-ABI provenance and native-integrity controls

**Scope:** P02 adds read-only, source-pinned checks for an ARM64 *debug/instrumentation* APK pair and an opt-in x86_64 *test-only* native artifact bundle. It never rebrands x86_64 as a production ABI, signs an APK, changes production Go/Android code, enables cutover, or certifies release readiness.

## What is added

- `scripts/mp12_p02_provenance.py`: independent bounded ZIP inspection, exact file inventories, duplicate/unsafe member refusal, full SHA-256 and byte-size checks, ELF64 little-endian ET_DYN, EM_AARCH64 vs EM_X86_64, minimum 16 KiB PT_LOAD alignment, arm64 source/receipt provenance, x86 source fingerprint, pinned NDK 29.0.14206865, aria2 source-build lock, and retained license/notice inventory.
- `scripts/test_mp12_p02_provenance.py`: offline real-byte fixtures with 33 adversarial/positive cases and deliberate mutation refusals; no synthetic Android execution claims.
- Existing `scripts/test_mp12_qualification.py` runs the P02 tests and P02 source-pinning guard within **the already-registered MP12 P01 hosted CI step**. Historical `.github/workflows/xgo-targeted.yml` is intentionally unchanged so MP04–MP08 immutable-CI checks stay valid.

## Source-only check (every PR targeted CI)

```sh
python3 -B scripts/test_mp12_p02_provenance.py
python3 -B scripts/mp12_p02_provenance.py source-only --repo .
```

These are executable source and fixture checks. They do **not** imply an actual artifact was built or executed.

## Inspect genuine artifacts (opt-in; after hosted builds)

The ARM64 input is the **exact directory** published by `scripts/xgo_hf16_apk_pair.py` containing `app-debug.apk`, `app-debug-androidTest.apk`, `SHA256SUMS`, and `APK_PAIR_RECEIPT.json`. The x86 input is the **inner** `native-output.zip` produced by `scripts/xgo_verified_native_artifact.py pack` for the same exact SHA, not the outer GitHub artifact ZIP wrapper. This verifies file provenance, not the truth of an unauthenticated off-host receipt or the execution of a source-build.

```sh
python3 -B scripts/mp12_p02_provenance.py verify-pair \
  --repo . \
  --expected-head "$(git rev-parse HEAD)" \
  --arm64-pair-dir /path/to/arm64-apk-pair \
  --x86-bundle /path/to/native-output.zip \
  --output "${TMPDIR:-/tmp}/mp12-p02-native-provenance.json"
```

The tool refuses stale commits, unexpected ABIs, absent libraries, wrong digests, insufficient ELF alignment, extra ZIP members, expired/missing inputs, missing source files and prebuilt aria2 locks. The output is a bounded, private, source-referenced audit receipt. Its `production_release_eligible`, `signed_android_qualified`, `physical_arm64_qualified`, and `go_cutover_authorized` fields remain `false` **even when the artifact check passes**.

## Next phases

P03: engine canary selection with explicit single-owner, durable before/after receipts and tested rollback; then signed-release workflows and independent desktop protocol parity. API36 x86 and physical ARM64 are separate test environments. Physical hardware, signing identity, licensed comparator, soak/chaos and manual device permissions remain separate gates. Never force-push, merge, tag, sign, install or publish through this P02 overlay.

## HF01 Termux report-writer portability

Use exclusive `os.open(..., O_CREAT|O_EXCL, 0600)` rather than `os.link`, which some Termux Python builds do not expose. The writer refuses existing destinations, symlink targets and a symlink parent, and removes partial receipts on synchronous write errors. This deliberately prioritizes no-clobber semantics; unlike temp+hardlink it cannot promise whole-file visibility across power loss. Six additional regression tests enforce the portable behavior.
