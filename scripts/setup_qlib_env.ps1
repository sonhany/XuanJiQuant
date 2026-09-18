param(
    [string]$PythonPath = "C:\Users\HYSHEN\AppData\Local\Programs\Python\Python311\python.exe",
    [string]$VenvPath = "",
    [string]$DataRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $VenvPath) {
    $VenvPath = Join-Path $projectRoot ".venv-qlib"
}
if (-not $DataRoot) {
    $DataRoot = Join-Path $projectRoot "data\qlib"
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python 3.11 not found: $PythonPath"
}

$version = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($version.Trim() -ne "3.11") {
    throw "Qlib environment requires Python 3.11, got $version"
}

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonPath -m venv $VenvPath
}

& $venvPython -m pip install --upgrade pip setuptools wheel
& $venvPython -m pip install -r (Join-Path $projectRoot "requirements-qlib.txt")

$directories = @(
    "raw\tdxquant",
    "raw\baostock",
    "raw\tencent",
    "raw\qlib_demo",
    "normalized\day",
    "normalized\calendar",
    "normalized\instruments",
    "normalized\corporate_actions",
    "qlib_bin\cn_data",
    "features",
    "experiments",
    "models",
    "predictions",
    "reports",
    "jobs"
)
foreach ($relative in $directories) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot $relative) | Out-Null
}

& $venvPython -c "import qlib, lightgbm, pandas, pyarrow, hmmlearn; import xgboost; print({'python':'3.11','qlib':getattr(qlib,'__version__','unknown'),'lightgbm':lightgbm.__version__,'xgboost':xgboost.__version__,'pandas':pandas.__version__,'pyarrow':pyarrow.__version__,'hmmlearn':hmmlearn.__version__})"
