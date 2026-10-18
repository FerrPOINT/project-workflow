param(
    [ValidateSet('test', 'test-verbose', 'test-integration', 'coverage', 'lint', 'quality', 'warnings', 'compose-ready', 'unit', 'integration', 'slow', 'release')]
    [string]$Target = 'quality'
)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & python (Join-Path $PSScriptRoot 'quality.py') $Target
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }
