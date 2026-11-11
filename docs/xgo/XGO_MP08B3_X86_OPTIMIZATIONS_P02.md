# MP08B3 P02 — seven-case native-media CI optimizations

## Verified starting point

* Stacked draft PR #25, source commit `20d5b06ab2e814cc3bfea5931a1d4945843c2a5b`.
* PR #24 independently qualified x86_64 FFmpeg 9.0.1, FFprobe 9.0.1 and source-built aria2 1.37.0 on API36.
* P01 ran all three native cases successfully but JUnit rejected `b3_03InterruptedPendingMediaStoreRowIsReconciled` before the four-case suite executed.

## This patch

1. Fix the Kotlin `runBlocking` test's JVM `void` return by ending the b3_03 block in `Unit`; all existing assertions remain unchanged. Update the exact source hashes in the independently checked P01 driver and its tests.
2. Enable `setup-gradle@v6` Basic provider writes on explicitly labeled, same-repository PRs; never cache `~/.gradle` twice. Cache remains PR-scoped by GitHub.
3. In the disposable x86_64 hosted checkout only, transform exact source-pinned FFmpeg and aria2 Gradle module files. Correct their JNI input/output paths to `x86_64`. Their native source-build Exec tasks are skipped only with `-Pxdm.preverifiedNativeRuntime=true`, verified same-repo GitHub runner and `XGO_X86_NATIVE_ATTESTED=yes` after independent source/ELF/license/lock verification. Normal ARM64 module source and all release paths remain unchanged.
4. Extend the ABI-separated, content-keyed same-PR Actions cache to retain verified ELF outputs and provenance locks, not just the source/build object directories. On a cache hit, independently verify everything before skipping source compilation; a corrupted hit refuses. Upload one content-addressed x86_64 native artifact after successful native verification, independently tied to the source/ABI/NDK and the originating GitHub run. An opt-in later same-repository PR may reuse it only from a fully successful prior run, with exact fingerprint, manifest entry inventory, per-file SHA-256, ELF machine/alignment and post-restore lock verification. A miss builds from pinned source. A corrupt/mismatched candidate fails closed. Previously successful PR #24 has no such binary artifact; the first P02 run may still rebuild.
5. Save the object/source cache only after a real pinned-source build, never after importing a cross-PR artifact. Distinguish and report same-PR native reuse, cross-PR artifact reuse and pinned source builds, not after restoring binary artifacts.
6. Add source, native, APK and emulator per-stage timing plus native-artifact-vs-source mode to a job summary and downloadable redacted receipt.
7. Keep the same one KVM-backed API36 emulator and all seven actual tests, with independent JUnit/XML evidence. No success assertion from compilation or source tests alone.

## Limits

All local tests are offline/synthetic. The user-triggered hosted labeled job must prove the four MP08B3 cases and seven-test exact receipt. Physical ARM64, licensed 1DM+, source-built ARM64 requalification and production release remain separate.
