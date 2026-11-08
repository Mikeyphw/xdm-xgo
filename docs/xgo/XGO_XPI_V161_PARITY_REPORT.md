# XGO XPI v1.6.1 repository parity (XP01)

## Baseline

Repository `Mikeyphw/xdm-xgo`, `main` commit `7c87aef4942eaa3eaf8d87f7603014c28789127a`, tree `0533eed0e1746125406107c936fd40bdd1e95b93`.
Compared against the user-supplied nested XPI (`SHA-256 f76278a79be5c97e5cd2cd15c2d5f91fab175de0d87222d0d1c37d028c7d1add`).

The canonical Firefox Android source is `app/XDM.Android/browser-extension/src/main/extension/xdm-firefox`, **not** the separate desktop Chrome extension.
The original GitHub source packaged version `1.3.0`. The supplied XPI manifest is `1.6.1`, but its generated-config version is `1.6.0` (inconsistent).

## Changes

- Adopt the **seven different authored assets verbatim** from the reference: `extension.css`, `fab.js`, `frame-bridge.js`, `handoff.js`, `network-observer.js`, `popup.html`, `popup.js`.
- Six other authored assets are already byte-identical and remain unchanged: `bridge-selftest.js`, `candidate-store.js`, `detector-core.js`, `page-sniffer.js`, the two icon PNGs.
- Keep existing generated config/theme **templates** (runtime values are supplied per build and per app theme), update the manifest template to reflect the reference (retaining version token), and unify the source/Gradle/Python extension version as `1.6.1`. Set development unpacked output to the reference debug application ID, scheme, and default XDM target; keep separate release variants unchanged.
- Keep the Gecko ID, MV2 permissions, direct-v3 keyless XDM/1DM+ integration, dark/AMOLED variants, build determinism, Android export integration and existing release constraints.
- Add offline digest, render, legacy CI contract and package inventory assertions; wire into the Android PR CI and Gradle `jsTest` Node tests.

## Qualification

The new Python test verifies verbatim authored bytes against the original uploaded file's SHA-256 digests; reconstructs the reference debug variant with the corrected version; validates the rendered manifest/config/theme and extension contract; and refuses any drift.
GitHub Actions builds and tests; do not infer full browser behavior from static parity. Validate in Firefox/IronFox and Android on-device after successful hosted CI. No signing/tag/release job is modified. The original uploaded XPI was not signed or modified.

## XP01 HF01 — transactional preflight reliability

The first XP01 application was refused because the temporary/staged
`.devtool-artifact/payload/reference_files.zip` resolved to different bytes
than the reference bundle actually stored inside the overlay. The actual
reference bytes were verified. HF01 embeds the ZIP bytes in the content-hashed
preflight itself, verifies their SHA-256, then checks the exact SHA-256 of
all seven original authored assets. There is no staged nested-file lookup.

The retained Phase38 static validator is updated from the legacy
`idmdownload:` URI requirement to the pinned `intent:` handoff's
`scheme=idmdownload` and `package=idm.internet.download.manager.plus`
tokens, preserving its other source, privilege and release checks.
