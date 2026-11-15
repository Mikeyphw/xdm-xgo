# MP12 P06 — independent, fail-closed final qualification evidence

**Scope:** PR #28 (`feature/xgo-mp09-consolidated-recording-20261111`).
**Baseline:** MP12 P01–P05 source-only capabilities are present. P06 does not
promote any unverified condition to a production release.

## Delivered, independently runnable checks

1. `scripts/mp12_p06_final_qualification.py source-only --repo .` validates
   twelve historical Git blob pins and critical signing, x86 opt-in, physical
   ARM64 device and Go canary rollback policy markers. Source tests are NOT
   signed artifact, Android device, real desktop or licensed-comparator proof.
2. `python3 -B scripts/test_mp12_p06_final_qualification.py` tests 38
   independent positive/negative cases: exact PR head, latest-run failure
   precedence, run/job identity, actual five-case API36 markers, secret-free
   reports, output write safety and read-only ARM64 ADB probes.
3. `go test -count=1 ./runtime/canary` (engine cwd) runs the P03 Go runtime
   controller and eight new P06 adversarial crash/concurrency cases.
   `go test -race -count=1 ./runtime/canary` is mandatory in hosted Ubuntu
   CGO Linux/amd64 CI; not available on Android/ARM64 Termux.
4. `scripts/mp12_p06_final_qualification.py live --repo .` reads **actual**
   same-HEAD GitHub runs and required jobs with authenticated gh. Real API36
   Compose proof requires both the job result and the recorded five-test log.
   Report is intentionally bounded, private, URL/token/serial-free, and
   incapable of setting `release_qualified` or `production_cutover_authorized`
   true. Optional `--output /private/path.json` uses O_EXCL with 0600 mode.
5. `scripts/mp12_p06_final_qualification.py physical-preflight --serial
   localhost:5555` checks only ADB connection, ABI, SDK and emulator flags;
   does **not** install APKs, run instrumentation or qualify the device.

## Qualification still outstanding

- Full **real physical ARM64** APK-pair source provenance, instrumentation,
  media transfer and crash/restart acceptance. The existing user-supplied
  `scripts/run_physical_arm64_instrumentation.sh` installs two APKs and is **not**
  invoked by P06; device writes require explicit user authorization.
- The explicit-label, real x86_64 native build/API36 job must run at the same
  exact PR head; the existing opt-in workflow is not triggered automatically.
- An independently signed release and XAR16 binary/signature evidence from
  a real tag-gated release run. No signing secrets or tag are touched here.
- Actual desktop OS/native host ↔ Firefox extension end-to-end capture journeys,
  not just the P05 read-only protocol adapter.
- Any lawful licensed 1DM+ differential comparator, reproducible performance,
  fault injection, and explicit user-visible limitations acceptance.

The MP12 P01 ledger contains **11 gates**. P06 reports hosted/source gates
separately and keeps all independent release-critical gates marked
`not_qualified`. Even a green source-only P06 is not a production cutover.

## Safety / limitations

Never force-push, merge, sign, tag, upload a signed release, enable production
Go, install APKs, root, wipe, or change the user's device settings. Never
interpret the five API36 Compose tests as physical ARM64 evidence. Previous
MP11/P02/P03/P04/P05 source guards remain intact, including the CI05 workflow
and signed-release job byte pins. PR/head drift causes hard refusal.
