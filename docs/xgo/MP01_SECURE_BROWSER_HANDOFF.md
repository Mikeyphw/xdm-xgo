# XDM MP01 — app-export paired encrypted Firefox media capture

**Base:** `Mikeyphw/xdm-xgo` `main` commit `cbebbb03a9a36266977e6cd5e7403900857a94a3`, tree `14be39a314ef78c631435955cf1684f5fc99ade8`. MP00 PR #9 merged. No local Gradle builds.

## Security changes

1. On **user-requested XPI export from XDM Android**, XDM obtains its AndroidKeyStore-backed RSA public key (3072-bit, legacy-compatible RSA-OAEP with SHA-1/MGF1-SHA1), fingerprint and accepted OAEP hash. Only *public* material is included in the generated, manually installed Firefox extension. Neither private key nor credentials are exported as files.
2. The extension captures one user-selected logical media item only. It uses WebCrypto to generate a fresh AES-256-GCM key and 96-bit IV, encrypts the complete capture object, binds session/key ID using AES-GCM AAD, then RSA-OAEP wraps the symmetric key. The navigation URI contains only version, session ID, app key fingerprint, wrapped key, IV, ciphertext. Content can include authorized headers and exact signed URL *inside authenticated ciphertext*.
3. Final-sent HTTP request headers are eligible for execution only when they correspond to the selected request ID, generation and frame, with fresh `webRequest` provenance. Page hints cannot be promoted into Authorization/Cookie evidence. No captured header bag is injected into the page FAB script. The page-facing picker gets synthetic, credential-free display URLs and metadata only; the exact URLs remain private in the extension background store until user selection.
4. Unpaired/keyless developer XPIs cannot export authenticated media: only a URL without query/fragment/URI credentials (and without captured auth/cookie evidence) may be sent to ordinary Add review. Signed/authenticated media fails closed with no navigation.
5. The Android deep-link parser rejects **all** old direct-v3 capture links, including seemingly public ones; safe public URLs use the ordinary Add review instead. Legacy encrypted-v2 parser and app-private ciphertext-only import journal remain supported.
6. After a successful encrypted import, the app-private journal records a hash-only completed-session tombstone before deleting the recoverable ciphertext. A repeated external launch with the same session ID cannot re-import it, including after process restart; interrupted imports can still recover.

## Important limitations / outstanding acceptance

- An **app public key encrypts to the app but does not authenticate the Firefox sender**. Malicious applications can obtain the XPI public key and encrypt a capture for user review. The exported activity intentionally still requires explicit user approval and applies XDM's existing external URL policies. Do not claim cryptographic sender authentication or perfect origin/redirect isolation until a stronger paired channel is implemented and tested.
- This change does **not** yet prove redirect-hop Authorization/Cookie isolation inside FFmpeg/HTTP executors. Do not accept cross-origin credential forwarding until MP01's device/network negative tests have run. The runtime must fail closed where this cannot be guaranteed.
- It does not make DRM-protected streams downloadable. 1DM+ ARM64 reference behavior remains untested.
- The generic release/CI-generated **keyless** XPI intentionally cannot capture authenticated media. **Regenerate the XPI from inside XDM Android after installing the new APK**, replace the previously installed extension, and confirm the correct app variant. A previously installed old-v3 XPI will be rejected if it sends plaintext secrets.
- Browser DevTools/WebExtensions keep detected media and headers briefly in extension memory; clearing all potential browser-level logs is platform-dependent and is not an MP01 acceptance claim.
- All tests in the existing repository, including source validators asserting the old v3 behavior, must be requalified on GitHub after applying. Source/Gradle/device/PR execution is NOT claimed as completed from this builder alone.

## Minimum manual acceptance before merging

1. Source-pinned overlay generated, verified, applied via Devtool autocommit and pushed to temporary MP01 branch.
2. GitHub Android CI and XDM Modern CI green; `:browser-extension:jsTest`, Kotlin browser-integration tests and app import journal tests green. On failure, inspect tests rather than weakening security assertions.
3. Android app generates a new paired XPI; installing that XPI leads to one user-approved, decryptable capture from MP00's HLS/DASH fixture. Validate native public key RSA wrap via ARM64 device test.
4. Verify raw `xdmdownload:` links, dumps, logs, exported XPI, session summaries do not contain test Cookie, Bearer, signed URL, or session secrets. Repeated `sid` blocked, expired and tampered ciphertext refused, mismatched request/frame proof cannot authorize headers.
5. Cross-origin redirects and suspicious HTTP headers must be tested on device. Do not merge if secrets are forwarded across unapproved redirect hops.

## Installer

Unpack this kit then run `zsh APPLY_MP01.zsh` in Termux. The wrapper verifies the exact upstream SHA and tree, refuses dirty/unexpected worktrees, creates the feature branch, generates a consolidated Devtool overlay using SHA-1-pinned original files with SHA-256 manifest preimages, lets Devtool autocommit, pushes and opens a PR. No local Gradle invocation.
