param(
    [ValidateSet("test", "test-integration", "coverage", "lint", "quality", "warnings", "compose-ready")]
    [string]$Target = "quality",
    [string]$CliBase = $env:WORKFLOW_CLI_BASE
)

$ErrorActionPreference = "Stop"
$Uv = @("uv", "run", "--isolated", "--with-requirements", "constraints.txt", "--all-extras")

function Invoke-Checked {
    param([string[]]$Command)

    & $Command[0] @($Command[1..($Command.Length - 1)])
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Initialize-SharedCli {
    if (-not $CliBase) {
        $CliBase = Join-Path $PSScriptRoot "../../workflow-cli-base"
    }
    $Revision = & git -C $CliBase rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $Revision -ne "278be4a2eb0b3ce49dac2cd14ea7e2871f2ffe1d") {
        throw "CLI Base must be the qualified checkout; set WORKFLOW_CLI_BASE or -CliBase (see docs/quality-gate.md)."
    }
    $Changes = & git -C $CliBase status --porcelain --untracked-files=all
    if ($LASTEXITCODE -ne 0 -or $Changes) {
        throw "CLI Base checkout must be clean."
    }
    $Core = (Resolve-Path -LiteralPath (Join-Path $CliBase "base-modules/python/cli-core")).Path
    $env:PYTHONPATH = (@($Core, $env:PYTHONPATH) | Where-Object { $_ }) -join [IO.Path]::PathSeparator
}

function Invoke-Test {
    Invoke-Checked ($Uv + @("python", "-B", "-m", "scripts.run_pytest", "-q", "--timeout=60"))
}

function Invoke-TestIntegration {
    Invoke-Checked ($Uv + @("python", "-B", "-m", "scripts.run_pytest", "-q", "-m", "integration", "--timeout=120"))
}

function Invoke-Coverage {
    Invoke-Checked ($Uv + @("python", "-B", "-m", "scripts.run_pytest", "--cov=project_workflow", "--cov-report=term", "--timeout=60"))
}

function Invoke-Lint {
    Invoke-Checked ($Uv + @("ruff", "check", "."))
    Invoke-Checked ($Uv + @("mypy", "project_workflow", "scripts"))
}

function Invoke-Warnings {
    Invoke-Checked (
        $Uv + @(
            "python", "-B", "-m", "scripts.run_pytest",
            "-q",
            "--timeout=60",
            "-W",
            "error::ResourceWarning",
            "-W",
            "error::pytest.PytestUnraisableExceptionWarning"
        )
    )
}

function Invoke-ComposeReady {
    Invoke-Checked @("docker", "compose", "up", "--build", "-d", "--wait")
    Invoke-Checked @("curl.exe", "--fail", "http://127.0.0.1:8812/health")
}

if ($Target -in @("test", "test-integration", "coverage", "quality", "warnings")) {
    Initialize-SharedCli
}

switch ($Target) {
    "test" { Invoke-Test }
    "test-integration" { Invoke-TestIntegration }
    "coverage" { Invoke-Coverage }
    "lint" { Invoke-Lint }
    "quality" {
        Invoke-Checked @("python", "-B", "scripts/check_repository_hygiene.py", "--index")
        Invoke-Coverage
        Invoke-TestIntegration
        Invoke-Lint
    }
    "warnings" { Invoke-Warnings }
    "compose-ready" { Invoke-ComposeReady }
}
