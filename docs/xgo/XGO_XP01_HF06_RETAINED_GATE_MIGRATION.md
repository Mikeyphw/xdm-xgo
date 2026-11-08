# XP01 HF06 — Retained Firefox extension validation gates

## Scope
Replaces **failed HF05** after its transactional rollback. Exact source commit:
`b237e60335066928203b719c226a06ce61388db4` on `feature/xgo-xpi-v161-parity-20261108`.

## Changes
- Includes the entire HF05 Parity02 and Phase43A single-selected-media migration, with no need to apply HF05 first.
- Phase43A release verifier checks for `bridge-selftest.js` within the actual `REQUIRED_FILES` set instead of requiring old whitespace formatting or a specific first entry.
- Phase43A Devtool integration now checks real `jsTest`, Kotlin `test`, and `validateFirefoxExtension` tasks, while separately requiring the Gradle `verifyFirefoxExtensionReleaseArtifacts` gate for release packaging.
- Phase43A accepts the verified XAR17 `next_phase` as a legitimate successor, while rejecting unexpected roadmap drift.
- The XP01 Python regression runs both retained source validators and checks the three new requirements.

## Preserved
All 16 canonical Firefox extension files, their XFE01 16-file digest seal, the 1.6.1 source parity digests, browser ID and manifest permissions, one selected XDM/1DM+ handoff, HF20 native runtime, and signed-release workflow are untouched.

## Verification limits
The overlay's preflight and offline simulation can be verified without Android SDK or Gradle. The actual Devtool apply and full GitHub-hosted Android CI remain acceptance gates.
