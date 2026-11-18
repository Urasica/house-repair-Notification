[CmdletBinding()]
param([ValidateSet('Start', 'Stop')][string]$Action = 'Start')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$localUrl = 'http://localhost:18880'
$composeArgs = @('--host', 'npipe:////./pipe/dockerDesktopLinuxEngine', 'compose',
    '--project-name', 'repair-guide-local', '--env-file', '.env.example', '-f', 'compose.yaml')

function Invoke-Compose([string]$Step, [string[]]$Command, [switch]$Admin) {
    $ErrorActionPreference = 'Continue'
    $arguments = $composeArgs
    if ($Admin) { $arguments += @('-f', 'compose.admin.yaml') }
    & docker @arguments @Command
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (Docker exit $LASTEXITCODE)." }
}

try {
    Set-Location -LiteralPath $root
    if (-not (Get-Command docker -CommandType Application -ErrorAction SilentlyContinue)) {
        throw 'Install and start Docker Desktop with Linux containers.'
    }

    # Exported Compose variables take precedence over --env-file, including DB URLs.
    foreach ($line in Get-Content -LiteralPath '.env.example') {
        if ($line -match '^([A-Z][A-Z0-9_]*)=') {
            Remove-Item -LiteralPath ('Env:' + $Matches[1]) -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue
    $env:WEB_PORT = '18880'
    $env:WEB_ORIGINS = '["' + $localUrl + '"]'

    New-Item -ItemType Directory -Path '.cache' -Force | Out-Null
    $localDeployLock = [IO.File]::Open((Join-Path $root '.cache/local-deploy.lock'), 'OpenOrCreate', 'ReadWrite', 'None')

    if ($Action -eq 'Stop') {
        Invoke-Compose 'Stopping the local server' @('down')
        Write-Host 'Local server stopped. Database volume retained.'
        exit 0
    }

    $catalog = Get-Item -LiteralPath 'data/catalog/m08a-20261004/catalog.json'
    $catalogMount = $catalog.FullName.Replace('\', '/') + ':/catalog.json:ro'
    Invoke-Compose 'Building the local images' @('build', 'api', 'web')
    Invoke-Compose 'Starting the database' @('up', '-d', '--wait', 'db')
    Invoke-Compose 'Stopping the old web and API' @('stop', 'web', 'api')
    Invoke-Compose 'Updating the database schema' @('run', '--rm', '--no-deps', 'api', 'python', '-m', 'alembic', 'upgrade', 'head') -Admin
    Invoke-Compose 'Publishing the reviewed catalog' @('run', '--rm', '--no-deps', '--volume', $catalogMount,
        'api', 'python', '-m', 'app.commands.catalog', 'publish', '/catalog.json')
    Invoke-Compose 'Starting the local server' @('up', '-d', '--no-build', '--wait', 'api', 'web')
    Write-Host "Local server: $localUrl"
    Write-Host 'Stop with stop-test-deploy.bat.'
} catch {
    [Console]::Error.WriteLine('FAILED: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($localDeployLock) { $localDeployLock.Dispose() }
}
