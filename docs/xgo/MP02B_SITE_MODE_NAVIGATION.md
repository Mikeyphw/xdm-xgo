# MP02B — Firefox extension site-mode and navigation evidence retirement

## Scope

- Revokes all logical candidates, alias maps, privileged per-request evidence, captured headers, diagnostics and pending auto-offer timers when site-mode / allowlist / blocklist / capture-enabled settings change.
- Enforces extension-owned top-level tab/frame sender origin policy before page-body or frame-playback hints can affect candidate state; page hints remain untrusted and never gain executable header authority.
- Avoids classifying a CDN/media **request URL** as if it were the document site for whitelist/blacklist rules. Unknown initiator/document is rejected under restricted site modes; when an earlier matching privileged request has document provenance, it can still be correlated.
- Drops pending captured headers on tab navigation or close, maintains scoped iframe retirement, and clears dispatch session state on full navigation.
- Adds executable Node/browser-API simulations and Python source/security checks to targeted CI. Preserves the manual Android/Modern/media full workflows and the five-integration full-gate router.

## Limits

This is **MP02B**, not full EXT01–EXT12 completion. The main-world page-sniffer can remain injected when disabled but is deactivated by frame-bridge controls; the security boundary is the privileged background listener which discards disabled hints and revokes cached request evidence. No Android native build, hosted emulator, physical ARM64 acceptance or Firefox live pairing is claimed by these checks. Site-mode modifications are a conservative fail-closed policy trade-off for requests whose embedding origin cannot be proven.

## Tests

- `node app/XDM.Android/browser-extension/tests/test_mp02b_site_mode.js`
- `python3 -B scripts/test_xgo_mp02b_source_contract.py`
- existing `test_background.js`, `test_detector.js`, `test_mp02_discovery.js`, XAR10, and XFE01/XPI provenance tests.
