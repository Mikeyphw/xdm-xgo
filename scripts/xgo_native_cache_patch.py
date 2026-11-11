#!/usr/bin/env python3
"""Source-pinned release workflow cache patch; never bypass native verification.

The self-launching Devtool archive materializes the ARM64 workflow only after
verifying the original Git blob at the requested checkout. This module has no
network, subprocess, or filesystem mutation in the transform routine.
"""
from __future__ import annotations

ARM64_ORIGINAL_BLOB = 'e8b85baa02a0076877c221709b361c5851bf4810'
ARM64_ANCHOR = '      - name: Build pinned ARM64 aria2 runtime from source\n'
ARM64_VALIDATE_ANCHOR = '      - name: Static release contracts\n'
ARM64_VALIDATE_AFTER = '      - name: Post-DL03 final common validation\n'
ARM64_AFTER = '      - name: Fetch provenance-pinned previous release fixture\n'
CACHE_FILES = (
    'app/XDM.Android/media-ffmpeg/runtime/ffmpeg-runtime.json',
    'app/XDM.Android/transfer-aria2/runtime/aria2-runtime.json',
    'app/XDM.Android/tools/install-ffmpeg-runtime.py',
    'app/XDM.Android/tools/build-aria2-runtime.py',
    'app/XDM.Android/tools/android_native_openssl.py',
    'app/XDM.Android/tools/android_elf_runtime.py',
)


def cache_key(abi: str) -> str:
    if abi not in {'arm64', 'x86_64'}:
        raise ValueError('XGO_NATIVE_CACHE_UNSUPPORTED_ABI')
    paths = list(CACHE_FILES)
    if abi == 'x86_64':
        paths += ['scripts/xgo_x86_native_media.py', 'scripts/xgo_x86_64_profile.py',
                  'tools/xgo/build_android_xdmcore_x86_64.py']
    args = ', '.join(repr(p) for p in paths)
    # Pin OS, NDK, recipe family and ABI; no broad restore-keys fallbacks.
    return '${{ runner.os }}-ndk29.0.14206865-' + abi + '-native-v2-${{ hashFiles(' + args + ') }}'


def cache_steps(abi: str) -> tuple[str, str, str]:
    if abi not in {'arm64', 'x86_64'}:
        raise ValueError('XGO_NATIVE_CACHE_UNSUPPORTED_ABI')
    parent = 'arm64' if abi == 'arm64' else 'x86'
    key = cache_key(abi)
    paths = '\n'.join('            ${{ runner.temp }}/'+parent+'-'+name for name in ('ffmpeg','aria2','openssl'))
    setup = '''      - name: Initialize {abi} native source and object cache directories
        shell: bash
        run: |
          set -euo pipefail
          test -n "${{RUNNER_TEMP:-}}" && test -d "$RUNNER_TEMP" || exit 2
          test -n "${{GITHUB_ENV:-}}" && test -f "$GITHUB_ENV" || exit 2
          for directory in {parent}-ffmpeg {parent}-aria2 {parent}-openssl; do
            install -d -m 0700 "$RUNNER_TEMP/$directory"
          done
          printf 'XDM_FFMPEG_BUILD_CACHE=%s\\n' "$RUNNER_TEMP/{parent}-ffmpeg" >> "$GITHUB_ENV"
          printf 'XDM_ARIA2_SOURCE_CACHE_DIR=%s\\n' "$RUNNER_TEMP/{parent}-aria2" >> "$GITHUB_ENV"
          printf 'XDM_ANDROID_NATIVE_DEPS_CACHE=%s\\n' "$RUNNER_TEMP/{parent}-openssl" >> "$GITHUB_ENV"
          echo 'XGO_{abi_upper}_NATIVE_BUILD_CACHE_PATHS_READY'
'''.format(abi=abi,abi_upper=abi.upper().replace('-','_'),parent=parent)
    restore = '''      - name: Restore {abi} verified native source and object cache
        uses: actions/cache/restore@v4
        id: xgo-native-cache
        with:
          path: |
{paths}
          key: {key}
'''.format(abi=abi, paths=paths, key=key)
    save = '''      - name: Save {abi} verified native source and object cache
        if: steps.xgo-native-cache.outputs.cache-hit != 'true'
        uses: actions/cache/save@v4
        with:
          path: |
{paths}
          key: ${{{{ steps.xgo-native-cache.outputs.cache-primary-key }}}}
'''.format(abi=abi,paths=paths)
    return setup,restore,save


def patch_arm64_workflow(src: str) -> str:
    # Prevent unexpected second release job, overwritten anchors and drift.
    if (src.count('  signed-release:\n') != 1 or src.count('  validate:\n') != 1 or
        src.count(ARM64_ANCHOR) != 1 or src.count(ARM64_AFTER) != 1 or
        src.count(ARM64_VALIDATE_ANCHOR) != 1 or src.count(ARM64_VALIDATE_AFTER) != 1):
        raise ValueError('XGO_ARM64_CACHE_SOURCE_WORKFLOW_ANCHOR_DRIFT')
    if 'Restore arm64 verified native source and object cache' in src or 'actions/cache/save@v4' in src:
        raise ValueError('XGO_ARM64_CACHE_ALREADY_APPLIED_OR_UNREVIEWED')
    setup,restore,save = cache_steps('arm64')
    # The heavyweight validate lane warms the same ABI-pinned cache on main;
    # signed release tags may restore it where GitHub ref-scoping permits.
    validation_build = '''      - name: Produce and verify ARM64 native source-built media before common validation
        shell: bash
        run: |
          set -euo pipefail
          python3 tools/build-aria2-runtime.py --build-pinned
          python3 tools/install-ffmpeg-runtime.py --build-pinned
          python3 tools/verify-aria2-runtime.py --require-payload --require-16kb-alignment --require-source-build
          python3 tools/verify-ffmpeg-runtime.py --require-payload --require-16kb-alignment
'''
    src = src.replace(ARM64_VALIDATE_ANCHOR,setup+restore+ARM64_VALIDATE_ANCHOR,1)
    src = src.replace(ARM64_VALIDATE_AFTER,validation_build+save+ARM64_VALIDATE_AFTER,1)
    # `signed-release` contains release secrets: never cache its worktree,
    # keystore, APKs or logs; only exact native compiler object/source caches.
    src = src.replace(ARM64_ANCHOR, setup + restore + ARM64_ANCHOR, 1)
    verified = '''      - name: Verify both ARM64 native source-built runtimes before cache save
        shell: bash
        run: |
          set -euo pipefail
          python3 tools/verify-aria2-runtime.py --require-payload --require-16kb-alignment --require-source-build
          python3 tools/verify-ffmpeg-runtime.py --require-payload --require-16kb-alignment
'''
    src = src.replace(ARM64_AFTER, verified + save + ARM64_AFTER, 1)
    if src.count('actions/cache/restore@v4') != 2 or src.count('actions/cache/save@v4') != 2:
        raise ValueError('XGO_ARM64_CACHE_INCOMPLETE')
    return src
