param(
    [switch]$ConfirmDestructive
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $ConfirmDestructive) {
    throw "Pass -ConfirmDestructive to run marked disposable SQL tests."
}

foreach ($name in @(
    "OSTV_SQL_TEST_SERVER",
    "OSTV_SQL_TEST_AUTH",
    "OSTV_SQL_TEST_USER",
    "OSTV_SQL_TEST_SERVER_MARKER",
    "OSTV_SQL_TEST_CREDENTIAL_TARGET"
)) {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if (-not $value) {
        throw "Required SQL integration environment variable is missing: $name"
    }
    Set-Item -Path "Env:$name" -Value $value
}

$python = Join-Path $PSScriptRoot "..\venv\Scripts\python.exe"
$tests = Join-Path $PSScriptRoot "..\tests"
if (-not (Test-Path -LiteralPath $python)) {
    throw "The repository virtual environment is not configured."
}
try {
    $env:OSTV_SQL_INTEGRATION = "1"
    $env:OSTV_SQL_CLIENT_INTEGRATION = "1"
    $env:OSTV_SQL_DESTRUCTIVE_TESTS = "1"
    Remove-Item Env:\OSTV_SQL_TEST_PASSWORD -ErrorAction SilentlyContinue
    & $python -m unittest discover -s $tests `
        -p "test_sql_development_setup.py" -v
    if ($LASTEXITCODE -ne 0) {
        throw "SQL development setup guard tests failed."
    }
    & $python -m unittest discover -s $tests `
        -p "test_sql_integration_safety.py" -v
    if ($LASTEXITCODE -ne 0) {
        throw "Disposable SQL safety tests failed."
    }
    & $python -m unittest discover -s $tests `
        -p "test_sql_collaboration_integration.py" -v
    if ($LASTEXITCODE -ne 0) {
        throw "Disposable SQL integration tests failed."
    }
    & $python -m unittest discover -s $tests `
        -p "test_sql_environment_integration.py" -v
    if ($LASTEXITCODE -ne 0) {
        throw "SQL development environment acceptance tests failed."
    }
    & $python -m unittest discover -s $tests `
        -p "test_sql_client_development_integration.py" -v
    if ($LASTEXITCODE -ne 0) {
        throw "Persistent SQL client environment tests failed."
    }
    & $python (Join-Path $PSScriptRoot "..\tools\audit_sql_integration_environment.py")
    if ($LASTEXITCODE -ne 0) {
        throw "SQL development environment cleanup audit failed."
    }
}
finally {
    Remove-Item Env:\OSTV_SQL_INTEGRATION -ErrorAction SilentlyContinue
    Remove-Item Env:\OSTV_SQL_CLIENT_INTEGRATION -ErrorAction SilentlyContinue
    Remove-Item Env:\OSTV_SQL_DESTRUCTIVE_TESTS -ErrorAction SilentlyContinue
    Remove-Item Env:\OSTV_SQL_TEST_PASSWORD -ErrorAction SilentlyContinue
}
