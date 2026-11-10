#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "app/XDM.Android/browser-extension/src/main/extension/xdm-firefox"
CANONICAL_ID = "xdm-android-media-bridge@mikeyphw"
EXPECTED_HASHES = {
    "bridge-selftest.js": "7c442bee5be87e6802e9f82f6fcca88daede13377fbbd70dd6e85216b0022eb6",
    "candidate-store.js": "21bd82e82b66bcdd521e14e349c65f3b26672ca7e9e7c5cba341d67fbc621d19",
    "detector-core.js": "071e2680bbf07c6be7841ad613c68043eec7427dbde36e32b5092d85f4e8bd65",
    "extension.css": "5f9d10da55bea57317d0f01db7a3a06ad4c4a196201a942027e25e751b6d4fcf",
    "fab.js": "42e44f689030d06687a651962c6306d0be58cb1bdfb6301e4038b8e52c2d286a",
    "frame-bridge.js": "e15b181cc1e87ff00d00855ac6f19b1fa8f893809abc2044df461d5f80a4f046",
    "generated-config.template.js": "0cd67c0565d9a1d94c2d8b0efe0e14e9c29565c926babe90208e07b7dac40033",
    "generated-theme.template.css": "b52a7938b8df6faf687e81f0a39899acf2fa89ff19a3d21b6a8508602acef735",
    "handoff.js": "23b649b98c6b3cbb4fbaa345d2cd654bbdfd6af40ab03eb54a64acfdcc20578e",
    "icons/icon48.png": "1ffad2f3f3e18ce0558fb506deb38c600f1747bb0dc0a5b1ad8c7ea448d8373b",
    "icons/icon96.png": "0f442e4f1c9075c0d8bdbe20a71102fa13bb6e603770010e78e1a87c27a7aa2f",
    "manifest.template.json": "e823a9405bfbbbcdffebefa06ae380ce783c0344e1ade80e6239893c01b47683",
    "network-observer.js": "c4b5280649c228d138c25ea22beec597c63b0ffdd09a826261d3d5feb7ad150e",
    "page-sniffer.js": "165ca7e2c610b3358b588d6c956ceb773a39d8b81d535a6aaf5f89ec4f74e63a",
    "popup.html": "d0eb8c568390257d470ff09bd61df1e385ebb36401f77bf8883408c26b9e4c31",
    "popup.js": "37b23978c3a5f786991b8f6bfac6f0e8fae17dcb056e62b54f230e059e615274",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit("XFE01 validation failed: " + message)


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def canonical_source_sha256(path: Path) -> str:
    # Git for Windows may check out text files using CRLF by default. The
    # attested payload is the canonical LF content; normalize *only* CRLF in
    # text resources. PNGs and other binary files are always byte-exact.
    payload = path.read_bytes()
    if path.suffix.lower() in {".js", ".css", ".html", ".json"}:
        if b"\r" in payload.replace(b"\r\n", b""):
            raise SystemExit("XFE01 validation failed: bare CR in canonical source: " + path.name)
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def verify_canonical_bytes() -> None:
    actual = {
        path.relative_to(CANONICAL).as_posix(): canonical_source_sha256(path)
        for path in sorted(CANONICAL.rglob("*"))
        if path.is_file()
    }
    require(actual == EXPECTED_HASHES, "canonical Android Firefox source changed; XFE01 must adapt desktop around it, not alter it")


def verify_single_source() -> None:
    retired = ROOT / "app/XDM/firefox-amo"
    require(retired.is_dir(), "legacy Firefox location must remain as an explicit non-executable tombstone for overlay compatibility")
    retired_manifest = json.loads((retired / "manifest.json").read_text(encoding="utf-8"))
    require(retired_manifest.get("retired") is True, "legacy Firefox manifest was not retired")
    require("manifest_version" not in retired_manifest, "legacy Firefox tree is still a loadable WebExtension")
    require(retired_manifest.get("canonical_extension_id") == CANONICAL_ID, "legacy Firefox tombstone does not point to the canonical ID")
    legacy_js = list(retired.rglob("*.js"))
    require(legacy_js and all("XFE01_RETIRED_FIREFOX_FORK" in item.read_text(encoding="utf-8") for item in legacy_js), "legacy Firefox executable logic still remains")
    csproj = text("app/XDM/src/XDM.BrowserMedia.Tests/XDM.BrowserMedia.Tests.csproj")
    require("XDM.Android/browser-extension/src/main/extension/xdm-firefox" in csproj, "desktop Firefox fixtures do not consume canonical source")
    require("firefox-amo" not in csproj, "desktop tests still reference the removed Firefox fork")
    parity = text("docs/parity/features.json")
    require("app/XDM/firefox-amo" not in parity, "active parity inventory still points at the removed Firefox fork")


def verify_desktop_adapter() -> None:
    parser = text("app/XDM/src/XDM.BrowserIntegration/FirefoxExtensionHandoffParser.cs")
    require(f'CanonicalExtensionId = "{CANONICAL_ID}"' in parser, "desktop parser canonical extension identity mismatch")
    require('ReleaseScheme = "xdmdownload"' in parser and 'DebugScheme = "xdmdownload-debug"' in parser, "desktop parser scheme mismatch")
    require('action == "add" && version != 1' in parser and '|| action == "capture"' in parser, "desktop public-Add-only handoff policy is missing")
    require('Encrypted browser captures require the paired Android app' in parser, "desktop does not explicitly reject app-paired captures")
    require("finalHeaders ?? proposedHeaders" not in parser, "proposed Firefox headers can become runtime authority")
    require("Authorization and Range are intentionally not promoted" in parser, "desktop least-privilege replay guard missing")

    installer = text("app/XDM/src/XDM.BrowserIntegration/BrowserHostInstaller.cs")
    require("FirefoxExtensionHandoffParser.CanonicalExtensionId" in installer, "browser repair does not bind to canonical Firefox ID")
    require("RegisterFirefoxProtocolAsync" in installer, "Firefox custom protocol registration missing")
    require("allowed_extensions" not in installer, "desktop still creates a Firefox native-messaging allow-list")
    require("RemoveLegacyFirefoxNativeMessagingManifest" in installer, "legacy Firefox native-messaging cleanup missing")

    program = text("app/XDM/src/XDM.App/Program.cs")
    coordinator = text("app/XDM/src/XDM.Platform/SingleInstanceCoordinator.cs")
    view_model = text("app/XDM/src/XDM.App/ViewModels/MainWindowViewModel.cs")
    require("FindHandoffArgument(args)" in program and "SignalPrimaryAsync(App.InitialFirefoxHandoffUri)" in program, "desktop process launch does not forward canonical handoff")
    require("MaximumActivationPayloadBytes = 64 * 1024" in coordinator and "ActivationRequestedEventArgs" in coordinator, "single-instance payload bridge missing or unbounded")
    require("HandleFirefoxExtensionHandoffAsync" in view_model and "FirefoxExtensionHandoffParser.TryParse" in view_model, "desktop UI path is not consuming canonical handoffs")


def verify_packaging() -> None:
    desktop = text("app/XDM/packaging/linux/xdm-modern.desktop")
    require("Exec=/opt/xdm/XDM %u" in desktop, "Linux desktop entry does not accept protocol URI")
    require("x-scheme-handler/xdmdownload;" in desktop and "x-scheme-handler/xdmdownload-debug;" in desktop, "Linux desktop entry missing Firefox handoff schemes")
    require(f"X-XDM-FirefoxExtensionId={CANONICAL_ID}" in desktop, "Linux desktop entry canonical ID marker missing")
    require("package-canonical-firefox-extension.py" in text("app/XDM/eng/publish-one.sh"), "Linux publish does not ship canonical Firefox XPI")
    require("package-canonical-firefox-extension.py" in text("app/XDM/eng/publish-one.ps1"), "Windows publish does not ship canonical Firefox XPI")

    with tempfile.TemporaryDirectory(prefix="xfe01-") as temporary:
        xpi = Path(temporary) / "XDM-Firefox.xpi"
        subprocess.run(
            [sys.executable, str(ROOT / "app/XDM/eng/package-canonical-firefox-extension.py"), "--output", str(xpi), "--theme", "dark", "--channel", "release"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        require(xpi.is_file() and xpi.stat().st_size > 0, "canonical Firefox XPI was not produced")
        with zipfile.ZipFile(xpi) as archive:
            names = archive.namelist()
            require(len(names) == 16 and len(names) == len(set(names)), "canonical Firefox XPI inventory is unexpected")
            require(all(".." not in Path(name).parts and not name.startswith("/") for name in names), "canonical Firefox XPI contains unsafe path")
            manifest = json.loads(archive.read("manifest.json"))
            require(manifest["browser_specific_settings"]["gecko"]["id"] == CANONICAL_ID, "packaged Firefox ID diverged")
            require("nativeMessaging" not in manifest.get("permissions", []), "canonical Firefox XPI unexpectedly gained nativeMessaging")


def main() -> int:
    verify_canonical_bytes()
    verify_single_source()
    verify_desktop_adapter()
    verify_packaging()
    print("XFE01 single Firefox extension convergence: PASS")
    print("canonical Firefox source files: 16/16 match current Android-owned baseline")
    print("desktop executable Firefox forks remaining: 0")
    print("desktop handoff contract: public Add v1; paired encrypted v2 is Android-only; plaintext capture v3 rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
