#!/usr/bin/env python3
"""Build and verify a genuine Android/x86_64 Go JNI core using pinned NDK 29.

This is a separate build profile. The proven ARM64 builder remains unchanged.
No host Linux libraries and no ARM64 translation are accepted as x86 evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NDK_VERSION = "29.0.14206865"
API = 26
ABI = "x86_64"
GOARCH = "amd64"
OUTPUT = ROOT / "app/XDM.Android/app/src/main/jniLibs/x86_64/libxdmcore.so"
HEADER = ROOT / "app/XDM.Android/app/src/main/jniLibs/x86_64/libxdmcore.h"
PROVENANCE = ROOT / "app/XDM.Android/app/src/main/assets/xdmcore/xdmcore-provenance.json"
EXPECTED_JNI = (
    "nativeCreate", "nativeCommand", "nativeNextFrame", "nativePlatformReply",
    "nativeMetadata", "nativeShutdown", "releaseBuffer",
)


def call(*argv: str, env: dict[str, str] | None = None, cwd: Path = ROOT) -> str:
    return subprocess.check_output(argv, cwd=cwd, env=env, text=True, stderr=subprocess.STDOUT)


def find_ndk() -> Path:
    roots: list[Path] = []
    for var in ("ANDROID_NDK_ROOT", "ANDROID_NDK_HOME"):
        if os.environ.get(var):
            roots.append(Path(os.environ[var]))
    for var in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if os.environ.get(var):
            roots.append(Path(os.environ[var]) / "ndk" / NDK_VERSION)
    roots += [Path.home() / "Android/Sdk/ndk" / NDK_VERSION, Path.home() / "android-sdk/ndk" / NDK_VERSION]
    for root in roots:
        source = root / "source.properties"
        if not source.is_file():
            continue
        match = re.search(r"(?m)^Pkg\.Revision\s*=\s*(\S+)\s*$", source.read_text())
        if not match or match.group(1) != NDK_VERSION:
            continue
        if (root / "toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android26-clang").is_file():
            return root
    raise RuntimeError(f"XGO_X86_NDK_MISSING_OR_UNPINNED:{NDK_VERSION}")


def verify_elf(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise RuntimeError("XGO_X86_NOT_ELF64_LE")
    elf_type, machine = struct.unpack_from("<HH", data, 16)
    if elf_type != 3 or machine != 62:
        raise RuntimeError(f"XGO_X86_WRONG_ELF_TYPE_OR_MACHINE:{elf_type}:{machine}")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    entsize, number = struct.unpack_from("<HH", data, 54)
    if entsize < 56 or number == 0 or phoff + entsize * number > len(data):
        raise RuntimeError("XGO_X86_MALFORMED_PROGRAM_HEADERS")
    loads = []
    for index in range(number):
        start = phoff + index * entsize
        ph_type = struct.unpack_from("<I", data, start)[0]
        if ph_type == 1:
            alignment = struct.unpack_from("<Q", data, start + 48)[0]
            loads.append(alignment)
    if not loads or min(loads) < 16384:
        raise RuntimeError(f"XGO_X86_LOAD_ALIGNMENT:{loads}")
    inspector = shutil.which("llvm-readelf") or shutil.which("readelf")
    if not inspector:
        raise RuntimeError("XGO_X86_READELF_MISSING")
    dynamic = call(inspector, "-d", str(path))
    needed = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", dynamic)
    if "liblog.so" not in needed:
        raise RuntimeError("XGO_X86_MISSING_ANDROID_LIBLOG")
    if any(".so." in name or name in {"libsqlite3.so", "libc.so.6", "libz.so.1"} for name in needed):
        raise RuntimeError(f"XGO_X86_NON_ANDROID_DEPENDENCY:{needed}")
    symbols = call(inspector, "-Ws", str(path))
    missing = [name for name in EXPECTED_JNI if f"Java_com_mikeyphw_xdm_android_engine_JniNativeXdmCore_{name}" not in symbols]
    if missing:
        raise RuntimeError("XGO_X86_MISSING_JNI_EXPORTS:" + ",".join(missing))
    return {"abi": ABI, "elf_machine": machine, "load_alignments": loads,
            "needed": needed, "jni_exports": len(EXPECTED_JNI),
            "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def build() -> dict[str, object]:
    ndk = find_ndk()
    clang = ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android26-clang"
    jni_include = ndk / "toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/include"
    if not (jni_include / "jni.h").is_file():
        raise RuntimeError("XGO_X86_ANDROID_JNI_HEADERS_MISSING")
    go_version = call("go", "env", "GOVERSION").strip()
    revision = call("git", "rev-parse", "HEAD").strip()
    dirty = bool(call("git", "status", "--porcelain", "--untracked-files=no").strip())
    target = OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    HEADER.unlink(missing_ok=True)
    env = os.environ.copy()
    env.update({
        "GOOS": "android", "GOARCH": GOARCH, "CGO_ENABLED": "1",
        "CC": str(clang), "CC_FOR_TARGET": str(clang),
        "CGO_CFLAGS": f"-O2 -fPIC -isystem {jni_include}",
        "CGO_LDFLAGS": "-fuse-ld=lld -llog -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384",
    })
    flags = (f"-X github.com/subhra74/xdm/engine/api/v1.BuildRevision={revision} "
             f"-X github.com/subhra74/xdm/engine/api/v1.BuildModified={'true' if dirty else 'false'} "
             "-X github.com/subhra74/xdm/engine/api/v1.BuildMode=c-shared")
    subprocess.run(["go", "build", "-trimpath", "-buildvcs=false", "-buildmode=c-shared",
                    "-ldflags", flags, "-o", str(target), "./engine/bridge/cabi"],
                   cwd=ROOT, env=env, check=True)
    metadata = verify_elf(target)
    PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["go", "run", "./engine/cmd/xgo-provenance", "--revision", revision,
                    f"--modified={'true' if dirty else 'false'}", "--go-version", go_version,
                    "--goos", "android", "--goarch", GOARCH, "--build-mode", "c-shared",
                    "--output", str(PROVENANCE)], cwd=ROOT, check=True)
    if not HEADER.is_file():
        raise RuntimeError("XGO_X86_GENERATED_CGO_HEADER_MISSING")
    metadata.update({"goarch": GOARCH, "go_version": go_version,
                     "revision": revision, "ndk": NDK_VERSION, "android_api": API,
                     "native_arm64_executed": False})
    receipt = ROOT / ".devtool/reports/xgo/android-x86_64-core.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print("XGO_X86_NATIVE_CORE_BUILD_PASS:" + metadata["sha256"])
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.execute == args.verify_only:
        parser.error("choose exactly one of --execute or --verify-only")
    result = build() if args.execute else verify_elf(OUTPUT)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
