#!/usr/bin/env bash
# HF12: shared, Ubuntu 24.04-only Android emulator host-library and loader checks.
# Executed by both PR instrumentation and tag-gated signed-release jobs.
set -euo pipefail

[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_OS:-}" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo 'XDM_HF12_HOSTED_LINUX_X64_REQUIRED' >&2
  exit 2
}

mode="${1:-}"
case "$mode" in
  --prepare)
    command -v sudo >/dev/null || { echo '::error::XDM_HF12_SUDO_MISSING' >&2; exit 2; }
    command -v apt-get >/dev/null || { echo '::error::XDM_HF12_APT_MISSING' >&2; exit 2; }
    # Native Ubuntu 24.04 packages, not emulator binaries or downloaded scripts.
    # libpulse0 supplies libpulse.so.0 (Android emulator/qemu exit 127 otherwise).
    packages=(
      libpulse0 libgl1 libegl1 libnss3 libx11-6 libx11-xcb1 libxcb1
      libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0
      libfontconfig1 libfreetype6 libxcomposite1 libxcursor1 libxdamage1
      libxi6 libxtst6 libxrandr2 libxkbfile1 libasound2t64 libdbus-1-3
    )
    for attempt in 1 2 3; do
      if sudo apt-get update -qq && sudo env DEBIAN_FRONTEND=noninteractive \
          apt-get install -y -qq --no-install-recommends "${packages[@]}"; then
        echo 'XDM_HF12_EMULATOR_LIBRARIES_INSTALLED'
        exit 0
      fi
      if (( attempt == 3 )); then
        echo '::error::XDM_HF12_EMULATOR_LIBRARIES_INSTALL_FAILED' >&2
        exit 2
      fi
      sleep 10
    done
    ;;
  --verify)
    sdk_root="${2:-${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}}"
    [[ "$sdk_root" == /* ]] || { echo '::error::XDM_HF12_SDK_ROOT_INVALID' >&2; exit 2; }
    binary="$sdk_root/emulator/emulator"
    [[ -x "$binary" ]] || { echo "::error::XDM_HF12_EMULATOR_MISSING: $binary" >&2; exit 2; }
    [[ -d "$sdk_root/system-images/android-36/google_apis/x86_64" ]] || {
      echo '::error::XDM_HF12_API36_GOOGLE_APIS_IMAGE_MISSING' >&2
      exit 2
    }
    log_dir="${RUNNER_TEMP:-/tmp}"
    [[ -d "$log_dir" && -w "$log_dir" ]] || { echo '::error::XDM_HF12_LOG_DIR_INVALID' >&2; exit 2; }
    log="$log_dir/xdm-hf12-emulator-version-$$.log"
    if "$binary" -version >"$log" 2>&1; then
      sed -n '1,8p' "$log"
      rm -f -- "$log"
      echo 'XDM_HF12_EMULATOR_RUNTIME_PASS'
      exit 0
    else
      code=$?
      echo "XDM_HF12_EMULATOR_EXEC_FAILED: exit=$code" >&2
      cat "$log" >&2
      rm -f -- "$log"
      qemu="$sdk_root/emulator/qemu/linux-x86_64/qemu-system-x86_64"
      if [[ -f "$qemu" ]] && command -v ldd >/dev/null; then
        echo 'XDM_HF12_QEMU_SHARED_LIBRARY_DIAGNOSTICS:' >&2
        ldd "$qemu" >&2 || true
      fi
      echo '::error::XDM_HF12_EMULATOR_RUNTIME_FAILED' >&2
      exit 2
    fi
    ;;
  *)
    echo 'XDM_HF12_MODE_REFUSED: expected --prepare or --verify' >&2
    exit 2
    ;;
esac
