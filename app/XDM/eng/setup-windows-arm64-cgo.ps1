# XDM HF10: Native ARM64 cgo linker, pinned to an upstream LLVM-MinGW release asset.
# Intended for windows-11-vs2026-arm, before Go cgo/SQLite tests and packaging.
$ErrorActionPreference = 'Stop'
$expectedOs = (& go env GOOS).Trim()
$expectedArch = (& go env GOARCH).Trim()
if ($LASTEXITCODE -ne 0 -or $expectedOs -ne 'windows' -or $expectedArch -ne 'arm64') {
    throw "HF10 toolchain requires native Windows ARM64 Go: $expectedOs/$expectedArch"
}
if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) { throw 'RUNNER_TEMP is unavailable' }
$archiveUrl = 'https://github.com/mstorsjo/llvm-mingw/releases/download/20260908/llvm-mingw-20260908-ucrt-aarch64.zip'
$archiveSha256 = '7fe35f60407473c420ac72b25137f54385b0affd2c42efd507c0062fc626ab56'
$root = Join-Path $env:RUNNER_TEMP 'xdm-hf10-llvm-mingw-arm64'
$archive = Join-Path $root 'llvm-mingw-20260908-ucrt-aarch64.zip'
$extract = Join-Path $root 'expanded'
New-Item -ItemType Directory -Path $root -Force | Out-Null
$ok = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    try {
        Invoke-WebRequest -Uri $archiveUrl -OutFile $archive -MaximumRedirection 8
        $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $archiveSha256) { throw "LLVM-MinGW SHA256 mismatch: $actual" }
        $ok = $true
        break
    } catch {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        if ($attempt -eq 3) { throw }
        Start-Sleep -Seconds (2 * $attempt)
    }
}
if (-not $ok) { throw 'Unable to download verified LLVM-MinGW' }
New-Item -ItemType Directory -Path $extract -Force | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
$compiler = Get-ChildItem -LiteralPath $extract -File -Recurse -Filter 'aarch64-w64-mingw32-clang.exe' | Select-Object -First 1
if ($null -eq $compiler) { throw 'Pinned LLVM-MinGW is missing ARM64 MinGW clang driver' }
$triple = (& $compiler.FullName -dumpmachine).Trim()
if ($LASTEXITCODE -ne 0 -or $triple -notmatch '^aarch64-.*(windows|mingw)') {
    throw "Unexpected compiler target triple: $triple"
}
$env:CC = $compiler.FullName
$env:CGO_ENABLED = '1'
if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_ENV)) {
    "CC=$($compiler.FullName)" | Out-File -LiteralPath $env:GITHUB_ENV -Append -Encoding utf8
    'CGO_ENABLED=1' | Out-File -LiteralPath $env:GITHUB_ENV -Append -Encoding utf8
}
Write-Host "XDM_HF10_ARM64_CGO_READY: $triple; sha256=$archiveSha256"
