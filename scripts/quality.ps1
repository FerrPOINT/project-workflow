param(
    [ValidateSet("test", "test-integration", "coverage", "lint", "quality", "warnings", "compose-ready")]
    [string]$Target = "quality"
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

function Invoke-Test {
    Invoke-Checked ($Uv + @("pytest", "-q", "--timeout=60"))
}

function Invoke-TestIntegration {
    Invoke-Checked ($Uv + @("pytest", "-q", "-m", "integration", "tests/test_postgres_integration.py", "--timeout=120"))
}

function Invoke-Coverage {
    Invoke-Checked ($Uv + @("pytest", "--cov=project_workflow", "--cov-report=term", "--timeout=60"))
}

function Invoke-Lint {
    Invoke-Checked ($Uv + @("ruff", "check", "."))
    Invoke-Checked ($Uv + @("mypy", "project_workflow", "scripts"))
}

function Invoke-Warnings {
    Invoke-Checked (
        $Uv + @(
            "pytest",
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

switch ($Target) {
    "test" { Invoke-Test }
    "test-integration" { Invoke-TestIntegration }
    "coverage" { Invoke-Coverage }
    "lint" { Invoke-Lint }
    "quality" {
        Invoke-Test
        Invoke-TestIntegration
        Invoke-Coverage
        Invoke-Lint
    }
    "warnings" { Invoke-Warnings }
    "compose-ready" { Invoke-ComposeReady }
}
