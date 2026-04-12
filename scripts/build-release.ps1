[CmdletBinding()]
param(
    [string]$Version,
    [string]$OutputDir = "artifacts",
    [string]$VendorSource,
    [switch]$SourceOnly,
    [switch]$ReleaseOnly,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($SourceOnly -and $ReleaseOnly) {
    throw "Use either -SourceOnly or -ReleaseOnly, not both."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot ".."))
$pluginRoot = Join-Path $repoRoot "FuzVoicePreview"

if (-not (Test-Path -LiteralPath $pluginRoot -PathType Container)) {
    throw "FuzVoicePreview directory was not found under $repoRoot"
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-Date -Format "yyyyMMdd-HHmmss"
}

$resolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    [System.IO.Path]::GetFullPath($OutputDir)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir))
}

$buildSource = -not $ReleaseOnly
$buildRelease = -not $SourceOnly

$sourceArchiveName = "fuz-source-$Version.zip"
$releaseArchiveName = "FuzVoicePreview-release-$Version.zip"

function Resolve-AbsolutePath {
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [string]$BasePath
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Test-ExcludedPath {
    param(
        [Parameter(Mandatory)]
        [string]$RelativePath,
        [Parameter(Mandatory)]
        [string[]]$ExcludePatterns
    )

    foreach ($pattern in $ExcludePatterns) {
        if ($RelativePath -like $pattern) {
            return $true
        }
    }

    return $false
}

function Copy-TreeFiltered {
    param(
        [Parameter(Mandatory)]
        [string]$SourceRoot,
        [Parameter(Mandatory)]
        [string]$DestinationRoot,
        [string[]]$ExcludePatterns = @()
    )

    $resolvedSourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null

    function Copy-Node {
        param([string]$CurrentSource)

        foreach ($item in Get-ChildItem -LiteralPath $CurrentSource -Force) {
            $relativePath = [System.IO.Path]::GetRelativePath($resolvedSourceRoot, $item.FullName).Replace('\\', '/')
            if (Test-ExcludedPath -RelativePath $relativePath -ExcludePatterns $ExcludePatterns) {
                continue
            }

            $targetPath = Join-Path $DestinationRoot ([System.IO.Path]::GetRelativePath($resolvedSourceRoot, $item.FullName))
            if ($item.PSIsContainer) {
                New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
                Copy-Node -CurrentSource $item.FullName
                continue
            }

            $targetParent = Split-Path -Parent $targetPath
            if ($targetParent) {
                New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
            }

            Copy-Item -LiteralPath $item.FullName -Destination $targetPath -Force
        }
    }

    Copy-Node -CurrentSource $resolvedSourceRoot
}

function New-ZipArchive {
    param(
        [Parameter(Mandatory)]
        [string]$SourceDirectory,
        [Parameter(Mandatory)]
        [string]$ArchivePath
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }

    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $SourceDirectory,
        $ArchivePath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $true
    )
}

function Resolve-VendorDirectory {
    param(
        [string]$VendorSourcePath,
        [Parameter(Mandatory)]
        [string]$RepoRoot
    )

    $candidate = if ([string]::IsNullOrWhiteSpace($VendorSourcePath)) {
        Join-Path $pluginRoot "vendor"
    } else {
        Resolve-AbsolutePath -Path $VendorSourcePath -BasePath $RepoRoot
    }

    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        throw "Vendor directory was not found: $candidate"
    }

    foreach ($requiredChild in @("bin", "site-packages")) {
        $requiredPath = Join-Path $candidate $requiredChild
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Container)) {
            throw "Vendor directory is incomplete. Missing: $requiredPath"
        }
    }

    return [System.IO.Path]::GetFullPath($candidate)
}

$sourceExcludes = @(
    ".git",
    ".git/*",
    ".venv",
    ".venv/*",
    ".pytest_cache",
    ".pytest_cache/*",
    ".mypy_cache",
    ".mypy_cache/*",
    ".ruff_cache",
    ".ruff_cache/*",
    ".pytype",
    ".pytype/*",
    "artifacts",
    "artifacts/*",
    "build",
    "build/*",
    "dist",
    "dist/*",
    "htmlcov",
    "htmlcov/*",
    "*__pycache__*",
    "*.pyc",
    "*.pyo",
    "FuzVoicePreview/vendor/bin",
    "FuzVoicePreview/vendor/bin/*",
    "FuzVoicePreview/vendor/site-packages",
    "FuzVoicePreview/vendor/site-packages/*",
    "FuzVoicePreview/vendor/python",
    "FuzVoicePreview/vendor/python/*"
)

$releasePluginExcludes = @(
    "*__pycache__*",
    "*.pyc",
    "*.pyo",
    "vendor/bin",
    "vendor/bin/*",
    "vendor/site-packages",
    "vendor/site-packages/*",
    "vendor/python",
    "vendor/python/*"
)

$vendorExcludes = @(
    "*__pycache__*",
    "*.pyc",
    "*.pyo"
)

$outputDirRelativeToRepo = [System.IO.Path]::GetRelativePath($repoRoot, $resolvedOutputDir).Replace('\\', '/')
if ($outputDirRelativeToRepo -eq ".") {
    throw "Output directory must not be the repository root."
}
if (-not $outputDirRelativeToRepo.StartsWith("../", [System.StringComparison]::Ordinal)) {
    $sourceExcludes += @($outputDirRelativeToRepo, "$outputDirRelativeToRepo/*")
}

$outputDirRelativeToPlugin = [System.IO.Path]::GetRelativePath($pluginRoot, $resolvedOutputDir).Replace('\\', '/')
if ($outputDirRelativeToPlugin -eq ".") {
    throw "Output directory must not be the FuzVoicePreview directory."
}
if (-not $outputDirRelativeToPlugin.StartsWith("../", [System.StringComparison]::Ordinal)) {
    $releasePluginExcludes += @($outputDirRelativeToPlugin, "$outputDirRelativeToPlugin/*")
}

$sourceArchivePath = Join-Path $resolvedOutputDir $sourceArchiveName
$releaseArchivePath = Join-Path $resolvedOutputDir $releaseArchiveName

Write-Host "Repository root : $repoRoot"
Write-Host "Output directory : $resolvedOutputDir"
if ($buildSource) {
    Write-Host "Source archive   : $sourceArchivePath"
}
if ($buildRelease) {
    $vendorPreview = if ([string]::IsNullOrWhiteSpace($VendorSource)) {
        Join-Path $pluginRoot "vendor"
    } else {
        Resolve-AbsolutePath -Path $VendorSource -BasePath $repoRoot
    }
    Write-Host "Release archive  : $releaseArchivePath"
    Write-Host "Vendor source    : $vendorPreview"
}

if ($DryRun) {
    if ($buildRelease) {
        [void](Resolve-VendorDirectory -VendorSourcePath $VendorSource -RepoRoot $repoRoot)
    }
    Write-Host "Dry run completed."
    return
}

New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("fuz-release-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    if ($buildSource) {
        $sourceStageRoot = Join-Path $tempRoot ("fuz-source-" + $Version)
        Copy-TreeFiltered -SourceRoot $repoRoot -DestinationRoot $sourceStageRoot -ExcludePatterns $sourceExcludes
        New-ZipArchive -SourceDirectory $sourceStageRoot -ArchivePath $sourceArchivePath
        Write-Host "Created source archive: $sourceArchivePath"
    }

    if ($buildRelease) {
        $resolvedVendorDir = Resolve-VendorDirectory -VendorSourcePath $VendorSource -RepoRoot $repoRoot
        $releaseStageRoot = Join-Path $tempRoot ("FuzVoicePreview-release-" + $Version)
        $stagedPluginRoot = Join-Path $releaseStageRoot "FuzVoicePreview"

        New-Item -ItemType Directory -Path $releaseStageRoot -Force | Out-Null
        Copy-TreeFiltered -SourceRoot $pluginRoot -DestinationRoot $stagedPluginRoot -ExcludePatterns $releasePluginExcludes
        Copy-TreeFiltered -SourceRoot $resolvedVendorDir -DestinationRoot (Join-Path $stagedPluginRoot "vendor") -ExcludePatterns $vendorExcludes
        Copy-Item -LiteralPath (Join-Path $repoRoot "README.md") -Destination (Join-Path $releaseStageRoot "README.md") -Force

        New-ZipArchive -SourceDirectory $releaseStageRoot -ArchivePath $releaseArchivePath
        Write-Host "Created release archive: $releaseArchivePath"
    }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}