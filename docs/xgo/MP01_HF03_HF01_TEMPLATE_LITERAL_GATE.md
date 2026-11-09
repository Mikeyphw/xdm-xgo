# MP01 HF03 HF01 — Encrypted URI query segment validator repair

Context: PR #10, `Mikeyphw/xdm-xgo`, base `12c464136e8ef4d1bf8fb91f766e8b6db71f4013`. This recovery applies **on top of the already locally committed HF03**, rather than recreating/rebasing that commit.

## Defect

HF03 static gate checked `\`&ek=` and `\`&ct=` as if these query parameters started individual JavaScript template literals. Actual source constructs `kid+ek` together in one string and `iv+ct` together in a second string:

```javascript
`&kid=${encodeURIComponent(pairing.kid)}&ek=${base64Url(wrappedKey)}` +
`&iv=${base64Url(iv)}&ct=${base64Url(ct)}`;
```

## Correction

The final Phase13 gate now requires those **exact composite segments**, retaining the other assertions for app-paired v2 capture, RSA-OAEP/AES-GCM, authenticated JSON, ciphertext-only navigation, a public Add v1 fallback, secure test evidence, and rejection of plaintext header serialization.

## Invariants

- Verify local HEAD is the expected Devtool-created HF03 commit with parent exactly at the pinned base.
- Confirm both HF03 source files match the exact output of the original source-pinned builder (plus the original report), with no extra changed files or dirty worktree.
- Check secure JS handoff tokens against the current source.
- Preflight the **entire updated Phase13 gate in-memory**, using the checkout's real files, **before** Devtool writes anything.
- Apply an atomic two-file overlay through Devtool to create a new commit. Never reset or force-push.
- Run Phase13 gate and optional Node tests before fast-forward push.
- No local Gradle tasks. Hosted CI is required for full qualification.
