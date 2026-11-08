# XP01 HF03 — consolidated XAR10 and XFE01 browser source gate reconciliation

PR #3 target commit: `742113e4faf52347b520c6cef9cf0c2c2c6975cf` (tree `07e0821549ffc3a93c42a8c2e0d8c13b116c96aa`). This replaces **the failed HF02**. The original XP01 HF01 import is already on the branch. Do not reapply XP01 or HF01 or HF02.

## Root cause

HF02 carried a malformed historical `popup.html` SHA-256, 60 characters instead of the **64-character** XFE01 digest. It missed the `ba68` substring (`fb68ba68`). That made the transactional preflight reject an otherwise clean, correct XP01 branch. Devtool reported an atomic verified rollback.

## Both CI repairs, one overlay

- XDM Android CI XAR10: the new Firefox FAB still uses `attachShadow({ mode: "closed" })`, but removed an obsolete comment. The security contract tests the actual closed-root statement, FAB host metadata and one-selected-item network handoff.
- XDM Modern CI XFE01: the old 16-file SHA-256 baseline predates the user-approved Firefox v1.6.1 source. Update the eight changed source hashes to their verified reference digests; preserve all other hashes unchanged and keep hard fail on unexpected source changes.
- Strengthen XP01 Python tests: compare all **16** canonical Firefox source hashes against XFE01, then run the retained XFE01 desktop canonical-XPI validation.
- Guard malformed digest length before patching; source-pinned exact commit/tree and Git blob checks; no source writes until all checks pass.

No changes to the seven v1.6.1 adopted XPI assets, Android app code, desktop runtime, release signing, Gradle workflow, or native runtimes. Offline smoke is not a substitute for GitHub Actions or physical browser qualification.
