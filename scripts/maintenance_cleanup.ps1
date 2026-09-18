[CmdletBinding()]
param(
    [switch]$Apply,
    [ValidateRange(7, 365)]
    [int]$LogRetentionDays = 14
)

$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$sourceRoots = @('components', 'lib', 'quant', 'scripts', 'server', 'tests')
$protectedRoots = @('data', 'config', 'node_modules', '.venv-qlib', 'docs', 'Logo', 'public')
$candidates = New-Object System.Collections.Generic.List[object]

function Add-Candidate {
    param(
        [System.IO.FileSystemInfo]$Item,
        [string]$Reason
    )

    if ($null -eq $Item -or -not $Item.Exists) {
        return
    }

    $fullPath = [System.IO.Path]::GetFullPath($Item.FullName)
    $rootPrefix = $root.TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside workspace: $fullPath"
    }

    foreach ($protected in $protectedRoots) {
        $protectedPath = [System.IO.Path]::GetFullPath((Join-Path $root $protected)).TrimEnd('\')
        if ($fullPath.Equals($protectedPath, [System.StringComparison]::OrdinalIgnoreCase) -or
            $fullPath.StartsWith($protectedPath + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing protected path: $fullPath"
        }
    }

    $length = if ($Item.PSIsContainer) {
        (Get-ChildItem -LiteralPath $fullPath -Recurse -Force -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    } else {
        $Item.Length
    }
    if ($null -eq $length) { $length = 0 }

    $candidates.Add([pscustomobject]@{
        Path = $fullPath
        Bytes = [int64]$length
        Reason = $Reason
        IsDirectory = [bool]$Item.PSIsContainer
    })
}

foreach ($relative in @('.pytest_cache', 'dist')) {
    $item = Get-Item -LiteralPath (Join-Path $root $relative) -Force -ErrorAction SilentlyContinue
    Add-Candidate -Item $item -Reason 'regenerable build/test cache'
}

foreach ($relative in $sourceRoots) {
    $base = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $base -PathType Container)) { continue }

    Get-ChildItem -LiteralPath $base -Recurse -Force -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Candidate -Item $_ -Reason 'Python bytecode cache' }

    Get-ChildItem -LiteralPath $base -Recurse -Force -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
            ($_.Extension -in @('.pyc', '.pyo', '.tmp', '.temp') -or $_.Name.EndsWith('~'))
        } |
        ForEach-Object { Add-Candidate -Item $_ -Reason 'temporary generated file' }
}

$logCutoff = (Get-Date).AddDays(-$LogRetentionDays)
$logRoot = Join-Path $root 'logs'
if (Test-Path -LiteralPath $logRoot -PathType Container) {
    Get-ChildItem -LiteralPath $logRoot -Force -File -Filter 'server-*.log' -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $logCutoff } |
        ForEach-Object { Add-Candidate -Item $_ -Reason "server log older than $LogRetentionDays days" }
}

$uniqueCandidates = @($candidates |
    Sort-Object -Property @{Expression = { $_.Path.Length }; Descending = $false }, Path -Unique)
$totalBytes = [int64](($uniqueCandidates | Measure-Object -Property Bytes -Sum).Sum)

if ($Apply) {
    foreach ($candidate in $uniqueCandidates | Sort-Object -Property @{Expression = { $_.Path.Length }; Descending = $true }) {
        if (-not (Test-Path -LiteralPath $candidate.Path)) { continue }
        if ($candidate.IsDirectory) {
            Remove-Item -LiteralPath $candidate.Path -Recurse -Force
        } else {
            Remove-Item -LiteralPath $candidate.Path -Force
        }
    }
}

[pscustomobject]@{
    schema_version = 'maintenance_cleanup.v1'
    workspace = $root
    mode = if ($Apply) { 'applied' } else { 'preview' }
    log_retention_days = $LogRetentionDays
    candidate_count = $uniqueCandidates.Count
    reclaimable_bytes = $totalBytes
    reclaimable_mb = [math]::Round($totalBytes / 1MB, 2)
    protected = $protectedRoots
    items = $uniqueCandidates
} | ConvertTo-Json -Depth 5
