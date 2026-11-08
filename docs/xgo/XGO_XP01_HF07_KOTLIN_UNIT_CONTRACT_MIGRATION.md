# XP01 HF07 — Kotlin unit contracts aligned with Firefox v1.6.1

## Baseline
- PR #3: https://github.com/Mikeyphw/xdm-xgo/pull/3
- Feature commit: `250311f4bfe8c50134c6678a168f0c85e2b082bf`
- Feature tree: `f3bfed5b9a192ed5b573f24d3a2a9c87c87b5b83`
- Failed Android CI: https://github.com/Mikeyphw/xdm-xgo/actions/runs/42495535739

## Root cause
The Android release/source gates and Modern CI now pass, but 2 of 483
`:app:testDebugUnitTest` tests assert the retired multi-candidate background handoff
and obsolete `Send N to XDM` button. The canonical Firefox 1.6.1 source
requires one explicit picker selection, then one evidence-backed handoff.

## Scoped changes
- Update `BrowserCapturePhases59_61ContractTest` to require exact single-selection,
  no automatic prebuilt handoff, zero auto-captured count, and existing bounded
  media session serialization and candidate evidence.
- Update `MediaParity02LogicalMediaCaptureContractTest` to require the current
  single-selection popup for XDM and 1DM+, and forbid the removed batch button.
- Extend the existing XP01 Python parity tests to enforce both Kotlin contracts.
- No Firefox source bytes, Android runtime, Gradle build, permissions, desktop
  source, signing workflow, or release gates are changed.

## Validation
The overlay is pinned to the branch SHA, exact Git tree, and eight Git blobs.
It checks all preconditions and expected JavaScript safety tokens *before*
writing. Devtool owns the transaction and rollback on failure.
The validator reruns the existing XP01 Python suite, retained static gates, and
all seven Node tests if Node is present. Full Kotlin/Gradle validation runs on
GitHub Actions and is not claimed by this offline artifact.
