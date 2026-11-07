#!/usr/bin/env bash
# HF10: Cinderbox R48 proven API36 emulator + fail-closed XGO ARM64 translation gate.
set -euo pipefail
mode="${1:?Expected --device or --signed-release}"
[[ "$mode" == "--device" || "$mode" == "--signed-release" ]] || { echo 'XDM_EMULATOR_MODE_REFUSED' >&2; exit 2; }
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_OS:-}" == Linux ]] || { echo 'XDM_HOSTED_EMULATOR_ONLY' >&2; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'XDM_HOST_ARCH_REFUSED' >&2; exit 2; }
[[ "$(git -C "$repo_root" rev-parse HEAD)" == "${GITHUB_SHA:?}" ]] || { echo 'XDM_EMULATOR_SHA_REFUSED' >&2; exit 2; }
serial=emulator-5554
[[ "$(adb -s "$serial" get-state)" == device ]] || { echo 'XDM_EMULATOR_OFFLINE' >&2; exit 2; }
sdk="$(adb -s "$serial" shell getprop ro.build.version.sdk | tr -d '\r')"
qemu="$(adb -s "$serial" shell getprop ro.kernel.qemu | tr -d '\r')"
abis="$(adb -s "$serial" shell getprop ro.product.cpu.abilist | tr -d '\r')"
[[ "$sdk" == 36 && "$qemu" == 1 ]] || { echo "XDM_EMULATOR_IDENTITY_REFUSED: SDK=$sdk qemu=$qemu" >&2; exit 2; }
[[ ",$abis," == *,arm64-v8a,* ]] || { echo "XDM_ARM64_TRANSLATION_UNAVAILABLE: $abis" >&2; exit 2; }
[[ -r /dev/kvm && -w /dev/kvm ]] || { echo 'XDM_HOST_KVM_UNAVAILABLE' >&2; exit 2; }
printf 'XDM_EMULATOR_PREFLIGHT_PASS: sdk=%s abi=%s host=x86_64\n' "$sdk" "$abis"
cd "$repo_root/app/XDM.Android"
case "$mode" in
  --device) bash tools/run-bug-hunt-phase11-validation-matrix.sh --device-only ;;
  --signed-release)
    ./gradlew :app:connectedDebugAndroidTest
    bash tools/run-xar16-signed-release-gate.sh --ci ;;
esac
