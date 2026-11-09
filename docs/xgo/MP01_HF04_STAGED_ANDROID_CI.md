# MP01 HF04 — Encrypted metadata + staged/fail-closed Android and Modern CI

Source branch: `feature/xgo-mp01-secure-browser-envelope-20261109`.
Source commit: `a4356e638866a3ef851c2e2af831a1605aab531d`.

## Why this hotfix exists

Android CI 42638060721 progressed past Phase 13 and stopped at an obsolete WEB01/NAME01 assertion that expected metadata to appear in the historical plaintext handoff regression test. The MP01 secure capture transports media duration/artwork inside the app-paired RSA-OAEP / AES-GCM envelope; the unpaired direct Add route intentionally sends public URL only.

HF04 makes `test_secure_handoff.js` decrypt the real v2 envelope and assert preservation of `durationMs=630000` and `thumbnailUrl=https://img.example/poster.jpg`, with non-disclosure of the thumbnail URL in the navigation link. The WEB01 validator requires these executable security regression assertions instead of a plaintext-v3 test shape. The crypto and actual application implementation remain unchanged.

## Fast versus full CI policy

Every PR commit gets `hotfix-fast`, which runs **all existing static release validators** and all seven Firefox JavaScript suites. This lane has no Android SDK, NDK, Gradle, emulator, or APK build.

The expensive existing Android `validate` (Android SDK/NDK/Gradle, build, tests, lint and APK artifacts) and its dependent `emulator-compatibility` jobs do **not** run by default on each PR hotfix. They are still automatic on main branch pushes, release tags, and manually dispatched workflow runs. On a PR, add the label `xdm-full-ci` to opt into **both full build and emulator compatibility** on its current head. Workflow `pull_request` includes `labeled` and `unlabeled`, so toggling the label triggers a new run. Keeping the label on means future pushes also run full CI; remove it when returning to fast hotfix iteration.

Modern CI now also runs a lightweight `modern-fast` job (Firefox XFE01 source integrity, REM18 release matrix, staged-CI policy), deferring the full .NET OS matrix and Linux/Windows ARM64 native toolchains until the same `xdm-full-ci` label is present. The push-to-main, release, and manual full paths remain intact.

A separate `android-pr-merge-qualification` and `modern-pr-merge-qualification` jobs remains **red** unless all respective fast and full jobs have **all** succeeded (Android: full Gradle and emulator; Modern: OS matrix and both native ARM64 lanes) for that PR event. This deliberately prevents an attractive but dangerous 'skipped full CI = green checks' appearance. Configure branch protection to require `android-pr-merge-qualification` and `modern-pr-merge-qualification` (as well as other required checks) before merging; existing repo protection cannot be read or modified through this integration (HTTP 403). A manually dispatched workflow is useful diagnostically, but only a label-triggered PR full run can turn both PR merge gates green.

**No change to signed-release protections**, physical ARM64 device acceptance, or Android x86_64 opt-in instrumentation policies. `workflow_dispatch` still runs full validate. Neither a green fast lane nor a green emulator-compatibility lane constitutes physical ARM64 device acceptance.

## Final qualification, in Termux

Create `xdm-full-ci` label if missing using `gh label create xdm-full-ci -R Mikeyphw/xdm-xgo --color 0E8A16 --description 'Run full Android and Modern CI with hosted emulators/ARM64'`.

To qualify current PR #10: `gh pr edit 10 -R Mikeyphw/xdm-xgo --add-label xdm-full-ci`.

To return to fast-only iteration: `gh pr edit 10 -R Mikeyphw/xdm-xgo --remove-label xdm-full-ci`; this invalidates PR merge qualification until the full lane is rerun on the final head.

## Verification classification

The builder checks exact original Git blob SHAs and exact original branch commit, and refuses dirty or drifting worktrees. Offline patch/yaml/metadata tests run without Gradle. The installer additionally executes the WEB01 validator, real Node crypto tests when Node is installed, and the CI-tier contract before pushing. Full hosted Gradle/.NET/native ARM64/emulator status is **pending** until the new commit reaches GitHub.
