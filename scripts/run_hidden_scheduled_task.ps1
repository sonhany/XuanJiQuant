param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("paper_daily", "paper_intraday", "research_daily", "qlib_weekly", "strategy_weekly")]
    [string]$TaskKey
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$projectPython = (Get-Command python -ErrorAction Stop).Source
$qlibPython = Join-Path $projectRoot ".venv-qlib\Scripts\python.exe"

$taskSpecs = @{
    paper_daily = @{
        Python = $projectPython
        Script = Join-Path $projectRoot "scripts\f5_paper_execution.py"
        Arguments = @("--once")
    }
    paper_intraday = @{
        Python = $projectPython
        Script = Join-Path $projectRoot "scripts\f5_paper_intraday.py"
        Arguments = @("--once")
    }
    research_daily = @{
        Python = $projectPython
        Script = Join-Path $projectRoot "scripts\run_daily_research_pipeline.py"
        Arguments = @("--workers", "8")
    }
    qlib_weekly = @{
        Python = $qlibPython
        Script = Join-Path $projectRoot "scripts\research_training_scheduler.py"
        Arguments = @("--once", "--lane", "qlib")
    }
    strategy_weekly = @{
        Python = $qlibPython
        Script = Join-Path $projectRoot "scripts\research_training_scheduler.py"
        Arguments = @("--once", "--lane", "strategy")
    }
}

$spec = $taskSpecs[$TaskKey]
if (-not (Test-Path -LiteralPath $spec.Python -PathType Leaf)) {
    throw "Scheduled task Python not found: $($spec.Python)"
}
if (-not (Test-Path -LiteralPath $spec.Script -PathType Leaf)) {
    throw "Scheduled task runner not found: $($spec.Script)"
}

$processArguments = @('"' + $spec.Script + '"') + @($spec.Arguments)
$process = Start-Process `
    -FilePath $spec.Python `
    -ArgumentList $processArguments `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -Wait `
    -PassThru

exit [int]$process.ExitCode
