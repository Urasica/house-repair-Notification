[CmdletBinding()]
param(
    [ValidateSet('Start', 'Stop')][string]$Action = 'Start',
    [ValidateSet('Local', 'TunnelTest')][string]$Profile = 'Local',
    [ValidateRange(1, 65535)][int]$Port = 18081,
    [switch]$OpenTunnel
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

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

    $tunnelTest = $Profile -eq 'TunnelTest'
    if ($OpenTunnel) {
        if (-not $tunnelTest -or $Action -ne 'Start') {
            throw '-OpenTunnel requires a TunnelTest start.'
        }
        $tunnelCommand = Get-Command api-tunnel.cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $tunnelCommand) { throw 'Add api-tunnel.cmd to PATH, or start the test server without -OpenTunnel.' }
    }

    $envFiles = @('.env.example')
    $composeFiles = @('compose.yaml')
    $project = 'repair-guide-local'
    $lockName = 'local-deploy.lock'
    if ($tunnelTest) {
        $project = 'repair-guide-tunnel-test'
        $composeFiles += 'compose.tunnel-test.yaml'
        $lockName = 'tunnel-test-deploy.lock'
    } elseif (Test-Path -LiteralPath '.env' -PathType Leaf) {
        $project = 'repair-guide'
        if (Test-Path -LiteralPath '.env.ops' -PathType Leaf) {
            $envFiles += '.env.ops'
            $composeFiles += 'compose.deletions.yaml'
        }
        $envFiles += '.env'
    }

    # Compose would otherwise pick exported shell values over the selected files.
    foreach ($line in Get-Content -LiteralPath $envFiles) {
        if ($line -match '^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=') {
            Remove-Item -LiteralPath ('Env:' + $Matches[1]) -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue
    if ($tunnelTest) {
        $env:WEB_PORT = [string]$Port
        $env:WEB_ORIGINS = ConvertTo-Json -InputObject @("http://localhost:$Port", "http://127.0.0.1:$Port") -Compress
    } elseif ($project -eq 'repair-guide-local') {
        $env:WEB_PORT = '18880'
        $env:WEB_ORIGINS = '["http://localhost:18880"]'
    }
    $composeArgs = @('--host', 'npipe:////./pipe/dockerDesktopLinuxEngine', 'compose', '--project-name', $project)
    foreach ($file in $envFiles) { $composeArgs += @('--env-file', $file) }
    foreach ($file in $composeFiles) { $composeArgs += @('-f', $file) }

    New-Item -ItemType Directory -Path '.cache' -Force | Out-Null
    $localDeployLock = [IO.File]::Open((Join-Path $root ".cache/$lockName"), 'OpenOrCreate', 'ReadWrite', 'None')

    if ($Action -eq 'Stop') {
        Invoke-Compose 'Stopping the local server' @('down')
        Write-Host "Local server stopped ($project). Database volume retained."
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
    $binding = Invoke-Compose 'Finding the local address' @('port', 'web', '80')
    Write-Host ('Local server: http://' + $binding.Replace('127.0.0.1:', 'localhost:'))
    if ($tunnelTest) {
        Write-Host "Public test tunnel: api-tunnel -Port $Port -LocalHostHeader"
        Write-Host 'Stop the tunnel with Ctrl+C, then run stop-test-tunnel-deploy.bat.'
        if ($OpenTunnel) {
            $localDeployLock.Dispose()
            $localDeployLock = $null
            & $tunnelCommand.Source -Port $Port -LocalHostHeader
            if ($LASTEXITCODE -ne 0) { throw "api-tunnel exited with code $LASTEXITCODE." }
        }
    } else {
        Write-Host 'Stop with stop-test-deploy.bat.'
    }
} catch {
    [Console]::Error.WriteLine('FAILED: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($localDeployLock) { $localDeployLock.Dispose() }
}
