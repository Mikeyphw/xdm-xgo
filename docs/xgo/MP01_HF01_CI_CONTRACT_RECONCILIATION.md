# MP01 HF01 — Hosted CI contract reconciliation

**Pinned source:** PR #10 in `Mikeyphw/xdm-xgo`, commit
`af37825ec273cd2f583168f80b13be35c5f83976`.

This hotfix intentionally does not alter the MP01 Firefox encryption algorithm,
Android Keystore keys, the Android v3 denial, or the secure-import journal. It fixes
the *source compatibility gates* and desktop parity policy which had lagged behind
MP01's transition from plaintext capture v3 to encrypted v2:

1. Android Phase59–61 validator now **requires** app-instance pairing template,
   RSA-OAEP, AES-GCM, SHA-256/verified request evidence and opaque `kid/ek/iv/ct`
   tokens while **forbidding** unencrypted header/candidate URI query fields.
   All existing application/journal/Media intake checks remain enabled.
2. XFE01 retains its original exact 16-file source hash verification, directory
   ownership, no-double-fork rule, XPI packaging, and desktop adapter checks.
   Only the three canonical files already changed by PR #10 receive **fixed**
   regenerated SHA-256 hashes, after verifying Git blob SHA-1 and exact PR base.
3. Desktop Firefox handoff parser rejects `capture` protocol links, including
   legacy plaintext v3, instead of replaying captured cookies. The desktop
   single-source keyless XPI continues to use the explicit **Add v1** path for
   public-only media. Paired encrypted v2 capture remains Android-specific.
4. .NET parser/security regression tests now assert rejection of credential
   smuggling and the shared encrypted extension code, replacing stale v3 success
   assertions.
5. The MP00 suite runner now retains only a bounded `test_*.js:line` failure
   location. It does not persist or print captured stdout/stderr, keeping
   credentials and raw web data out of CI receipts.
6. The Node background test no longer requires the raw signed media URL to be
   serialized into the page. It positively requires an opaque display URL and
   verifies that request headers and sensitive query material are absent.

## Safety and incomplete qualification

- No validator is disabled or skipped; validation semantics were updated.
- `--no-validate` is intentionally restricted to Devtool overlay application;
  release qualification remains **mandatory on GitHub Actions**.
- The overlay is additive on the existing PR #10 branch; it will **not** reset
  or overwrite another SHA or a dirty checkout.
- This is not a completed real-device security qualification. Android 16
  Keystore OAEP round-trip, Firefox/XPI export, signed-HLS playback, same-origin
  header binding, cross-origin redirects, and lifecycle/replay need real tests.
- Node/Gradle/.NET full suites must pass on PR #10 after HF01 is pushed.

## Review checklist

- [ ] MP00 fixture, Node and Android JVM suites pass
- [ ] Android CI static contracts and Kotlin build pass
- [ ] Modern Linux and Windows .NET test suites and XFE01 seal pass
- [ ] Android API 36 emulator/instrumentation as configured in CI
- [ ] Manual Android 16: export XPI from installed XDM, reinstall extension,
      exercise encrypted HLS/DASH with headers and signed URLs
- [ ] Same-origin request credentials never cross an unauthorized redirect

**Do not merge until hosted CI and security acceptance are qualified.**
