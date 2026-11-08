# XP01 HF04 — consolidate Phase 59–61 and JavaScript test migration

PR #3 branch `feature/xgo-xpi-v161-parity-20261108` source commit `d9461d33cbc151b0dce34850a85465bc2a766a99` (Git tree `f0cd9d2aff9adabb73993cbd2b47c3edf36b571a`).

## Hosted failure addressed
Android CI run 42488608424 passes the XAR10/XFE01-related source seals and then fails Runtime Foundation Phase 59–61, because an old validator requires `visibleCandidates.slice(0, MAX_HANDOFF_CANDIDATES)` (obsolete automatic multiple candidate handoff).

The authorized Firefox v1.6.1 implementation intentionally does **not** prebuild privileged capture URI on automatic detection. It requires the user to open the picker and choose **exactly one** item before producing an XDM v3 or 1DM+ handoff. The validator now checks that actual protection, including empty prebuilt handoff fields, the `ids.length !== 1` refusal, exactly one candidate in the selected payload, and no former multi-item auto dispatcher.

## Regression coverage
- Update retained `test_fab.js` to exercise the closed Shadow DOM with a simulated browser that respects `mode: "closed"`, the legacy direct/ask compatibility, the picker dialog and exactly-one selection.
- Update retained `test_phase43a_bridge.js` to preserve closed-shadow truth and the background picker path with no prebuilt URI.
- Update retained `test_background.js` to assert that automatic discovery does not hand off until selection; explicitly select for metadata, HLS and proposed-header assertions; reject multi-item requests without navigation.
- Extend XP01 Python source contract with Phase 59–61 behavior checks and ensure the updated release gate executes in the same CI source matrix.

No modifications to any of the 16 canonical Firefox source assets, Android runtime, native libraries, app version, Desktop XFE01 baseline, or signed-release job. Existing XP01 authored source SHA-256 verification and XFE01 16-file source integrity remain in force.

## Verification boundary
An isolated preflight simulation, modernized FAB Node test against the user's exact XPI, focused real-XPI background Node test, and ZIP integrity checks run offline. Final GitHub-hosted Android CI and Firefox/IronFox on-device acceptance remain distinct requirements. Do not merge until CI succeeds.
