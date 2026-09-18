param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("api", "web")]
    [string]$Service
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$nativeHost = Join-Path $projectRoot "scripts\service_host.cmd"
if (-not (Test-Path -LiteralPath $nativeHost -PathType Leaf)) {
    throw "Native service host not found: $nativeHost"
}

Push-Location $projectRoot
try {
    & $env:ComSpec /D /C "`"$nativeHost`" $Service"
    exit [int]$LASTEXITCODE
}
finally {
    Pop-Location
}
