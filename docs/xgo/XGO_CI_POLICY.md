# XGO CI05 — targeted PR checks and periodic full gates

This mirrors the architecture of the user's AuroraStore-Standalone targeted-CI PR,
with XDM-specific Android, Modern, media-parity and Go requirements.

## What runs

| Event | Action |
| --- | --- |
| Every PR update | `XGO Targeted CI`: exact diff classification, selected real JS/Python/Go tests |
| Android Kotlin/Gradle source changes | Additional hosted Kotlin `:app:compileDebugKotlin` (no emulator, no entire Gradle suite) |
| Every integration to `main` | Targeted CI plus lightweight gate router |
| Every five first-parent `main` commits | Router dispatches all 4 full workflows and verifies 13 required jobs |
| Security, signing, CI infrastructure, native runtime or release changes | Immediate full gate after integration |
| Explicit manual full-gate request | Router dispatch on `main`, regardless of interval |
| Android release tag | Existing Android signed-release trigger and checks remain active |

**Default cadence:** `XGO_FULL_GATE_INTERVAL=5`, configurable as GitHub repository Actions variable (integer 1–25). A first-parent main commit is counted as **one integration unit**, not as one physical overlay ZIP. Squash merges are normally one unit. The stored baseline `cbebbb03a9a36266977e6cd5e7403900857a94a3` is only an **accounting anchor**, not an asserted full-gate success. The initial policy change is high risk and forces a real full gate after merge. A successful full gate produces `xgo-full-gate/<router-run-id>` tag on the exact SHA. A failed/incomplete gate produces no tag, and the counter is not reset.

## Full gate — retained, not removed

The old files `.github/workflows/android.yml`, `.github/workflows/modern-ci.yml`, `.github/workflows/media-parity.yml`, and `.github/workflows/devtool-xgo-engine.yml` are preserved in full and become workflow_dispatch-only; Android also retains `android-v*` signed release tag pushes. The router dispatches them against the exact `main` commit and requires these job sets:

- Android: `hotfix-fast`, `validate`, `emulator-compatibility`.
- Modern: `modern-fast`, `validate (ubuntu-latest)`, `validate (windows-latest)`, `native-linux-arm64`, `native-windows-arm64`.
- MP00: `MP00 playable HLS DASH server and evidence`, `MP00 existing Android media JVM regressions`, `MP00 existing Go and Firefox Node suites`.
- Engine: `source`, `engine`.

**13/13 mandatory hosted jobs** must finish successfully, with the exact SHA. Old PR merge-qualification jobs are retained for legacy compatibility but intentionally do not run on manual dispatch. The new targeted qualification job is clearly labeled **NOT full qualification**. A physical ARM64 phone and MP01 manual Firefox pairing/replay/cross-origin redirect verification are *not* checked by the hosted workflows and remain explicitly deferred.

No merge is performed by any CI script. No automatic release, license/DRM bypass, production promotion or false ARM64 receipt.

## How to use

- Routine overlay: native Devtool atomic apply+commit, `git push`, open stacked PR, wait for `XGO Targeted CI`. The workflow is source-bound, no local Gradle.
- Manual early full gate, **after the policy is integrated into main**:

```zsh
# Require Actions workflow permissions to allow dispatching and writing a successful source-bound tag.
gh workflow run xgo-full-gate-router.yml -R Mikeyphw/xdm-xgo --ref main
gh run list -R Mikeyphw/xdm-xgo --workflow xgo-full-gate-router.yml --limit 5
```

- Inspect full-gate tags: `git fetch --tags origin && git tag --list 'xgo-full-gate/*'`.
- Ordinary overlays should **not** add `xdm-full-ci`; that legacy label will no longer trigger full CI.
- Do not merge the stacked MP02A/policy PR while MP01 security gates remain unresolved if the merge is intended as production qualification. Routine changes can progress on the development branch, and all gates remain explicit.

## Temporary workflow and rollback

`xgo-targeted.yml`, `xgo-full-gate-router.yml` and `scripts/ci/*` may be removed when this development phase ends. Restore automatic triggers only in a separate reviewed CI-policy change. Preserve historical checkpoint tags as audit evidence. Any policy modification forces another full gate on the next main merge.

## GitHub Actions permission note

The full router needs `actions: write` to dispatch existing workflows and `contents: write` to create its successful full-gate tag. If these are denied by repository settings, it must fail closed and report a permissions issue rather than marking the gate successful. It is safe to complete targeted PR checks without these write permissions.
