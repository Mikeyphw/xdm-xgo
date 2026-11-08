#!/usr/bin/env bash
# XP02: x86_64 emulator-native Android framework/Room tests; never Go/JNI ARM64.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_OS:-}" == Linux ]] || { echo 'XGO_XP02_CI_HOST_REQUIRED' >&2; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'XGO_XP02_HOST_ABI_REFUSED' >&2; exit 2; }
[[ "$(git -C "$repo_root" rev-parse HEAD)" == "${GITHUB_SHA:?}" ]] || { echo 'XGO_XP02_HEAD_REFUSED' >&2; exit 2; }
serial=emulator-5554
[[ "$(adb -s "$serial" get-state)" == device ]] || { echo 'XGO_XP02_DEVICE_OFFLINE' >&2; exit 2; }
prop() { adb -s "$serial" shell getprop "$1" | tr -d '\r'; }
[[ "$(prop ro.kernel.qemu)" == 1 ]] || { echo 'XGO_XP02_PHYSICAL_DEVICE_REFUSED' >&2; exit 2; }
[[ "$(prop ro.product.cpu.abi)" == x86_64 ]] || { echo 'XGO_XP02_EMULATOR_ABI_REFUSED' >&2; exit 2; }
[[ "$(prop ro.build.version.sdk)" == 36 ]] || { echo 'XGO_XP02_API_REFUSED' >&2; exit 2; }
[[ -r /dev/kvm && -w /dev/kvm ]] || { echo 'XGO_XP02_KVM_REFUSED' >&2; exit 2; }
cd "$repo_root/app/XDM.Android"
command -v gradle >/dev/null || { echo 'XGO_XP02_GRADLE_MISSING' >&2; exit 2; }
# Only the persistence Android library instrumentation suite. No :app task, no native
# JNI/aria2/FFmpeg runtime loading, no ARM64 translation, no release-test claim.
rm -rf persistence/build/outputs/androidTest-results/connected
gradle --no-daemon --console=plain -Dorg.gradle.parallel=false :persistence:connectedDebugAndroidTest
python3 -B tools/verify-hosted-emulator-persistence-results.py \
  --results-dir persistence/build/outputs/androidTest-results/connected \
  --receipt "${RUNNER_TEMP:?}/xdm-emulator-persistence/receipt.json"
echo 'XGO_XP02_EMULATOR_PERSISTENCE_PASS: x86_64/API36 Room instrumentation (not native ARM64)'
