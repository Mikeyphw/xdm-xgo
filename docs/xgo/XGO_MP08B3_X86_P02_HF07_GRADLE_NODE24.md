# MP08B3 X86 P02 HF05 — Gradle Configuration Cache + Node24 + Go Cache

Base: existing draft PR #25 (`feature/xgo-mp08b3-x86-integrated-20261111`) at commit `7906571ed96380eebabd1b67f66335dfd4533d2e`.

## Failure confirmed
Hosted native run #43021484343 passed pinned native build and independent verification, then `:app:assembleDebug :app:assembleDebugAndroidTest` executed and built the APKs but Gradle failed persisting configuration cache because the ephemeral FFmpeg and aria2 `Exec.onlyIf` task execution closures captured the Gradle script object. This is **not** an APK compilation or library verification failure.

## Fix
- Retain strict configuration cache, remove the execution-time `onlyIf` closures. Resolve `xdm.preverifiedNativeRuntime` under host/provenance checks at **configuration time** and configure the existing native compiler tasks with `enabled = false` when source-built, independently verified payloads have already been staged. The tasks and independent verifiers remain registered; ordinary production ARM64 project files are never committed.
- Migrate the CI05 targeted workflow's old Node20 actions to Node24-ready major versions: `setup-node@v5`, `setup-go@v6`, `setup-java@v6`, `setup-gradle@v6`.
- Disable `setup-go`'s fragile shared `~/go` cache restore for the targeted and x86 test jobs; replace it with `actions/cache@v5` on distinct isolated `$RUNNER_TEMP` `GOMODCACHE` and `GOCACHE` directories, exact hash of `engine/go.mod` plus `engine/go.sum`, no `restore-keys`.
- Update both stale source-contract tests that explicitly required `setup-go@v5`.
- Add negative contracts proving a configuration-time skip only, no release/ARM64 bypass, no silenced configuration-cache errors, no reintroduction of Node20 action versions.

## Boundaries
- Pinned native FFmpeg/FFprobe/aria2 source or previously verified exact-input cache/artifact, independent ELF/lock verifier, APK payload equality, exact three native cases, and exact four MP08B3 cases remain mandatory.
- All Git/Devtool writes occur on the existing PR #25 feature branch. No merges, force pushes, or application to main. Run hosted CI, display real `gh` TUI, and report SUCCESS/FAILURE toasts and vibrations via Termux APIs.
- This hotfix has only local/source validation until the hosted API36 emulator seven-case run completes successfully. Avoid treating the three-case prior pass as a seven-case pass.

- Migrate the opt-in MP08B3 source/media/hosted workflow to Node24-compatible Python, Java, Gradle and artifact actions; preserve KVM and opt-in proof, updating the inherited exact-action KVM test.

## HF06 exact inherited-suite repair

The launcher now source-pins `scripts/test_xgo_native_cache_contract.py` at Git
blob `1cb66aaa8f1d08b1d628f95410e21fc931f5ff02` and updates its
`test_node24_actions_and_go_cache_path` to validate `cache: false`,
GOMODCACHE/GOCACHE and the exact keyed Node24 actions/cache@v5 instead of
requiring the incompatible removed setup-go `cache-dependency-path`.

HF06 local acceptance includes execution of the exact inherited native-cache
contract against the fully transformed workflow, not just launcher mock tests.
The launcher still runs every inherited staged test against the user's real
source checkout before applying or pushing.

## HF07 — exact dependent Git blob repair (validated before delivery)

HF06 changed `scripts/test_xgo_mp08b3_source_contract.py` from source blob
`eeb644a2a56c8cf6774b38a6ffac651dd0557263` to
`3e06a4a5a726cb68ce4ec2f4ffe250b5adde23fe`. The existing
`scripts/xgo_mp08b3_x86_integration.py check` still expected the old blob,
and its companion integration test also pinned the old value. HF07 adds both
exact-parent source-pinned files to the Devtool inventory and updates them
atomically. `render()` asserts the MP08B3 postimage Git blob to avoid stale
chain repairs. The launcher now runs executable source checks *before* the 11
longer inherited suites, so any future drift fails early. All prior Node24,
Gradle, native caching and seven-case fail-closed guards remain unchanged.

HF07 also repairs the optimize.py standalone synthetic negative check to include its newly mandatory android block; the integration regression suite runs that command line directly.
