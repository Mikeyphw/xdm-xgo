#!/usr/bin/env bash
# API36 emulator infrastructure checks ONLY. Deliberately never starts ARM64 Go JNI.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_OS:-}" == Linux ]] || { echo XGO_COMPAT_HOST_REFUSED >&2; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { echo XGO_COMPAT_HOST_ARCH_REFUSED >&2; exit 2; }
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
[[ "$(git -C "$repo_root" rev-parse HEAD)" == "${GITHUB_SHA:?}" ]] || { echo XGO_COMPAT_COMMIT_REFUSED >&2; exit 2; }
[[ -r /dev/kvm && -w /dev/kvm ]] || { echo XGO_COMPAT_KVM_REFUSED >&2; exit 2; }
serial=emulator-5554
[[ "$(adb -s "$serial" get-state)" == device ]] || { echo XGO_COMPAT_ADB_OFFLINE >&2; exit 2; }
prop() { adb -s "$serial" shell getprop "$1" | tr -d '\r'; }
[[ "$(prop ro.kernel.qemu)" == 1 ]] || { echo XGO_COMPAT_NOT_EMULATOR >&2; exit 2; }
[[ "$(prop ro.build.version.sdk)" == 36 ]] || { echo XGO_COMPAT_SDK_MISMATCH >&2; exit 2; }
[[ "$(prop ro.product.cpu.abi)" == x86_64 ]] || { echo XGO_COMPAT_ABI_MISMATCH >&2; exit 2; }
[[ "$(prop sys.boot_completed)" == 1 ]] || { echo XGO_COMPAT_NOT_BOOTED >&2; exit 2; }
adb -s "$serial" shell cmd package list packages >/dev/null || { echo XGO_COMPAT_PACKAGE_MANAGER_FAILED >&2; exit 2; }
adb -s "$serial" shell pm list instrumentation >/dev/null || { echo XGO_COMPAT_INSTRUMENTATION_SERVICE_FAILED >&2; exit 2; }
echo 'XGO_EMULATOR_COMPATIBILITY_PASS: API36/KVM/ADB/package-manager; native ARM64 still excluded'
bash "$repo_root/app/XDM.Android/tools/run-hosted-emulator-persistence-tests.sh"
