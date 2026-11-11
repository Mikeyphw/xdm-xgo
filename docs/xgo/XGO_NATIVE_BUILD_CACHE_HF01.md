# XGO native build caching HF01 (x86_64 + ARM64)

Scope: XGO x86_64 opt-in media acceptance (draft PR #24) and the existing
ARM64 heavyweight validation and signed-release jobs. Never grants emulator, physical ARM64, 1DM+, or release
qualification. All Gradle, NDK, and .NET builds remain in GitHub Actions.

The existing source builders already maintain deterministic caches:
`tools/install-ffmpeg-runtime.py`, `tools/build-aria2-runtime.py`, and their
shared OpenSSL authority. On each fresh Actions runner these are normally lost.
HF01 restores only their dedicated cache directories from GitHub Actions cache,
then invokes both source-build entry points and strict verifiers as before.
An exact, complete cache hit reuses the verified native source/object trees;
otherwise the builders compile from pinned sources. Cache entries are saved
immediately after `verify-aria2-runtime.py --require-source-build` and
`verify-ffmpeg-runtime.py --require-payload` succeed, even if a later emulator
or release step fails. No APKs, release keys, signed outputs, credentials,
workspaces or diagnostic logs are ever stored in the native cache.

Keys are split by architecture (ARM64 versus x86_64), Ubuntu runner OS, pinned
NDK revision 29.0.14206865, exact source/build manifests, source build recipes,
OpenSSL implementation, and x86 profile sources. No permissive prefix restore
is allowed. On every cache hit the existing scripts recheck their source locks,
measured toolchain, binary digests, Android ELF machine, 16 KiB PT_LOAD,
licenses and forbidden dependencies; a cache never replaces these checks.

The heavyweight ARM64 validation job can warm a verified cache on main;
the signed-release job attempts to restore the same key.

GitHub caches are branch/ref scoped. Reuse depends on availability of the exact
key in the ref's permitted cache scope; separate release tags cannot be
assumed to share caches. Cache expiry, size limits and toolchain drift still
cause legitimate rebuilds. The x86 job must only run after the explicit
`xgo-x86-native-media` PR label; ordinary CI05 targeted checks stay light.

The ARM64 workflow patch is generated only from original `android.yml` Git
blob `e8b85baa02a0076877c221709b361c5851bf4810` on source commit
`0867dfa8faa5dd41594ecbd20023aa6defbcd81b`. If the upstream file
changes, the launcher refuses rather than risk editing a different release
graph. The Python/Rich launcher creates the complete native Devtool v2 archive
for the exact checkout before Devtool applies it.
