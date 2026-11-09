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
# Alternative upstream GitHub Release API for the SAME verified release asset.
# Neither path changes the pinned version, expected size or expected checksum.
$archiveApiUrl = 'https://api.github.com/repos/mstorsjo/llvm-mingw/releases/assets/551256614'
$archiveExpectedBytes = 185605459L
$archiveSha256 = '7fe35f60407473c420ac72b25137f54385b0affd2c42efd507c0062fc626ab56'
$root = Join-Path $env:RUNNER_TEMP 'xdm-hf10-llvm-mingw-arm64'
$archive = Join-Path $root 'llvm-mingw-20260908-ucrt-aarch64.zip'
$extract = Join-Path $root 'expanded'
New-Item -ItemType Directory -Path $root -Force | Out-Null
# Transient GitHub/CDN 5xx errors are retried via the original release URL
# and the official GitHub release-asset API. The archive MUST be the same 185MB
# asset and MUST match the original SHA-256 before extraction or execution.
$ok = $false
$maxAttempts = 6
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    $useApi = ($attempt % 2 -eq 0)
    $sourceUrl = if ($useApi) { $archiveApiUrl } else { $archiveUrl }
    $sourceName = if ($useApi) { 'GitHub Release API' } else { 'upstream release asset' }
    try {
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        $requestArgs = @{
            Uri = $sourceUrl
            OutFile = $archive
            MaximumRedirection = 8
            TimeoutSec = 180
            ErrorAction = 'Stop'
        }
        if ($useApi) {
            $requestArgs.Headers = @{
                Accept = 'application/octet-stream'
                'User-Agent' = 'XDM-pinned-ARM64-toolchain'
                'X-GitHub-Api-Version' = '2022-11-28'
            }
        }
        Invoke-WebRequest @requestArgs
        $actualSize = (Get-Item -LiteralPath $archive).Length
        if ($actualSize -ne $archiveExpectedBytes) {
            throw "Pinned LLVM-MinGW asset size mismatch ($actualSize bytes)"
        }
        $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $archiveSha256) {
            throw 'Pinned LLVM-MinGW SHA256 mismatch; refusing unverified archive'
        }
        $ok = $true
        Write-Host "XDM_HF02_TOOLCHAIN_VERIFIED: $sourceName; attempt=$attempt; sha256=$archiveSha256"
        break
    } catch {
        $reason = $_.Exception.Message
        Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
        if ($attempt -ge $maxAttempts) {
            throw "Pinned ARM64 compiler unavailable after $maxAttempts attempts; last source=$sourceName; reason=$reason"
        }
        $delay = [int][Math]::Min(30, 3 * [Math]::Pow(2, $attempt - 1))
        Write-Warning "XDM_HF02_TOOLCHAIN_RETRY: $sourceName attempt=$attempt/$maxAttempts; retry in ${delay}s"
        Start-Sleep -Seconds $delay
    }
}
if (-not $ok) { throw 'Unable to download SHA256-verified pinned LLVM-MinGW' }
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
