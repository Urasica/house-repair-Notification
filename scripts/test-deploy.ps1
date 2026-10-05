[CmdletBinding()]
param(
    [ValidateSet('Start', 'Stop', 'Status', 'Check', 'Daily')][string]$Action = 'Start',
    [switch]$Detached,
    [switch]$NoBuild,
    [switch]$NoOpenAI,
    [switch]$LocalOnly,
    [switch]$Tunnel,
    [ValidateRange(1024,65535)][int]$Port = 18880
)
$ErrorActionPreference = 'Stop'
if ($LocalOnly -and $Tunnel) { throw 'Choose LocalOnly or Tunnel, not both.' }
if (-not $Tunnel) { $LocalOnly = $true }
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$Private = Join-Path $Root 'data/private/preview'
$StatePath = Join-Path $Private 'state.json'
$EnvironmentPath = Join-Path $Root '.env.preview'
$Project = 'repair-guide-preview'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-Environment([string]$Path) {
    $values = @{}
    if (Test-Path -LiteralPath $Path) {
        foreach ($line in [IO.File]::ReadAllLines($Path)) {
            if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
                $value = $Matches[2].Trim()
                if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                    ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
                $values[$Matches[1]] = $value
            }
        }
    }
    return $values
}

function Write-Environment([hashtable]$Values) {
    $lines = foreach ($key in ($Values.Keys | Sort-Object)) {
        if ([string]$Values[$key] -match '[\r\n]') { throw "Multiline configuration is not supported: $key" }
        '{0}={1}' -f $key, $Values[$key]
    }
    [IO.File]::WriteAllLines($EnvironmentPath, [string[]]$lines, $Utf8)
}

function Random-Hex([int]$Length = 24) {
    $bytes = New-Object byte[] $Length
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($bytes) } finally { $random.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}

function Invoke-Docker([string[]]$Command, [switch]$Capture) {
    # Native stderr carries ordinary Docker progress too; check exit status explicitly.
    $ErrorActionPreference = 'Continue'
    $lines = & docker @Command 2>&1
    $resultCode = $LASTEXITCODE
    if ($Capture) {
        if ($resultCode -ne 0) { throw "Docker command failed (exit $resultCode)." }
        return ($lines | ForEach-Object { $_.ToString() }) -join "`n"
    }
    $lines | ForEach-Object { Write-Host $_.ToString() }
    if ($resultCode -ne 0) { throw "Docker command failed (exit $resultCode)." }
}

function Invoke-Compose([string[]]$Command, [switch]$Admin, [switch]$Ops, [switch]$Capture) {
    # Compose process environment overrides --env-file: set the generated isolated
    # values explicitly so inherited DATABASE_URL/POSTGRES_DB cannot target development.
    $values = Read-Environment $EnvironmentPath
    foreach ($key in $values.Keys) { [Environment]::SetEnvironmentVariable($key, $values[$key], 'Process') }
    $arguments = @('compose', '-p', $Project, '--env-file', $EnvironmentPath,
        '-f', 'compose.yaml', '-f', 'compose.prod.yaml', '-f', 'compose.deletions.yaml',
        '-f', 'compose.preview.yaml')
    if ($Admin) { $arguments += @('-f', 'compose.admin.yaml') }
    if ($Ops) { $arguments += @('-f', 'compose.ops.yaml') }
    Invoke-Docker -Command ($arguments + $Command) -Capture:$Capture
}

function Get-State {
    if (Test-Path -LiteralPath $StatePath) { return Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json }
    return $null
}

function Read-TunnelLog([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    $reader = New-Object IO.StreamReader($stream)
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
}

function Get-OwnedTunnel($State) {
    if (-not $State -or -not $State.processId) { return $null }
    $process = Get-Process -Id $State.processId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq 'cloudflared' -and
        $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $State.startTicks) {
        return $process
    }
    return $null
}

function Stop-Preview {
    $state = Get-State
    $tunnel = Get-OwnedTunnel $state
    if ($tunnel) { Stop-Process -Id $tunnel.Id -Force }
    if (Test-Path -LiteralPath $EnvironmentPath) { Invoke-Compose -Command @('down', '--remove-orphans') }
    if (Test-Path -LiteralPath $StatePath) { Remove-Item -LiteralPath $StatePath }
    Write-Host 'Preview stopped. Database and encrypted backups are retained.'
}

function Invoke-Daily {
    Invoke-Compose -Ops -Command @('run', '--rm', '--no-deps', 'ops', 'export-deletions')
    Invoke-Compose -Ops -Command @('run', '--rm', '--no-deps', 'ops', 'backup', '--reviewed', '/reviewed', '--local', '/backups', '--remote', '/remote')
    Invoke-Compose -Ops -Command @('run', '--rm', '--no-deps', 'ops', 'cleanup')
    $report = @{completedAt = [DateTime]::UtcNow.ToString('o'); remoteStorage = 'local-test-stand-in'}
    [IO.File]::WriteAllText((Join-Path $Private 'daily-success.json'), ($report | ConvertTo-Json), $Utf8)
}

function Initialize-Preview {
    $source = Read-Environment (Join-Path $Root '.env')
    $values = Read-Environment $EnvironmentPath
    if (-not $values.ContainsKey('POSTGRES_PASSWORD')) {
        $values['POSTGRES_PASSWORD'] = Random-Hex
        $values['POSTGRES_ADMIN_PASSWORD'] = Random-Hex
        $keyBytes = New-Object byte[] 32
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $random.GetBytes($keyBytes) } finally { $random.Dispose() }
        $values['BACKUP_KEY'] = [Convert]::ToBase64String($keyBytes).Replace('+','-').Replace('/','_')
    }
    $values['APP_ENV'] = 'production'
    $values['POSTGRES_DB'] = 'repair_guide_preview'
    $values['POSTGRES_USER'] = 'repair_guide'
    $values['DATABASE_URL'] = 'postgresql+psycopg://repair_guide:' + $values.POSTGRES_PASSWORD + '@db:5432/repair_guide_preview'
    $values['MIGRATION_DATABASE_URL'] = 'postgresql+psycopg://postgres:' + $values.POSTGRES_ADMIN_PASSWORD + '@db:5432/repair_guide_preview'
    $values['PREVIEW_PORT'] = "$Port"
    $values['PREVIEW_TARGET_PORT'] = if ($LocalOnly) { '443' } else { '80' }
    $values['PREVIEW_CADDYFILE'] = if ($LocalOnly) { 'Caddyfile.preview-local' } else { 'Caddyfile.tunnel' }
    $values['PUBLIC_DOMAIN'] = 'preview.invalid'
    $values['WEB_ORIGINS'] = '["https://preview.invalid"]'
    $values['RELEASE_TAG'] = 'm12-preview'
    $values['BACKUP_SCOPE'] = 'repair-guide-preview'
    $values['BACKUP_RETENTION_DAYS'] = '14'
    $values['DELETION_LOG_RETENTION_DAYS'] = '15'
    foreach ($pair in @(@('DELETION_EXPORT_DIR','deletions'), @('BACKUP_LOCAL_DIR','backups'),
                         @('BACKUP_REMOTE_DIR','remote-test'), @('RESTORE_FILES_DIR','restored'))) {
        $path = Join-Path $Private $pair[1]
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        $values[$pair[0]] = $path.Replace('\','/')
    }
    $values['REVIEWED_FILES_DIR'] = (Join-Path $Root 'data/private/m08/2026-10-04').Replace('\','/')
    if (-not (Test-Path -LiteralPath (Join-Path $values.REVIEWED_FILES_DIR 'manifest.json'))) {
        throw 'Reviewed source files are missing. Restore the protected M08 source folder first.'
    }
    $defaults = @{OPENAI_ENABLED='false'; OPENAI_API_KEY=''; OPENAI_CHAT_MODEL='gpt-5.4-mini';
        OPENAI_EMBEDDING_MODEL='text-embedding-3-large'; EMBEDDING_DIMENSIONS='1536';
        CHAT_USER_WINDOW_LIMIT='20'; CHAT_DAILY_LIMIT='100'; CHAT_MAX_OUTPUT_TOKENS='4096'}
    foreach ($key in $defaults.Keys) {
        $values[$key] = if ($source.ContainsKey($key)) { $source[$key] } else { $defaults[$key] }
    }
    if ($NoOpenAI) { $values['OPENAI_ENABLED']='false'; $values['OPENAI_API_KEY']='' }
    Write-Environment $values
    return $source
}

function Copy-ReviewedData([hashtable]$Source) {
    $count = Invoke-Compose -Capture -Command @('exec','-T','db','psql','-U','postgres','-d','repair_guide_preview','-Atc','SELECT count(*) FROM catalogs')
    if ($count.Trim() -ne '0') { Write-Host 'Existing preview data retained.'; return }
    $sourceContainer = Invoke-Docker -Capture -Command @('ps','--filter','label=com.docker.compose.project=repair-guide',
        '--filter','label=com.docker.compose.service=db','--format','{{.ID}}')
    if ($sourceContainer.Trim() -match '^[a-f0-9]{12,64}$' -and $Source.POSTGRES_DB -match '^[a-zA-Z0-9_]+$') {
        $temporary = '/tmp/preview-reference-' + [Guid]::NewGuid().ToString('N') + '.dump'
        $localFile = Join-Path $Private 'reference.dump'
        $targetContainer = (Invoke-Compose -Capture -Command @('ps','-q','db')).Trim()
        try {
            # Whitelist only reference tables. No users, sessions, results or questions.
            Invoke-Docker -Command @('exec',$sourceContainer.Trim(),'pg_dump','-U','postgres','-d',$Source.POSTGRES_DB,
                '--format=custom','--data-only','--no-owner','--no-acl','--table=catalogs','--table=knowledge_sets',
                '--table=knowledge_documents','--table=knowledge_chunks','--file',$temporary)
            Invoke-Docker -Command @('cp',($sourceContainer.Trim()+':'+$temporary),$localFile)
            Invoke-Docker -Command @('cp',$localFile,($targetContainer+':'+$temporary))
            Invoke-Compose -Command @('exec','-T','db','pg_restore','-U','postgres','-d','repair_guide_preview',
                '--data-only','--disable-triggers','--single-transaction','--exit-on-error','--no-owner','--no-acl',$temporary)
        } finally {
            Invoke-Docker -Command @('exec',$sourceContainer.Trim(),'rm','-f',$temporary)
            Invoke-Docker -Command @('exec',$targetContainer,'rm','-f',$temporary)
            if (Test-Path -LiteralPath $localFile) { Remove-Item -LiteralPath $localFile }
        }
        Write-Host 'Reviewed catalog/knowledge copied. No member or consultation data copied.'
    } else {
        $catalogMount = (Join-Path $Root 'data/catalog').Replace('\','/') + ':/data/catalog:ro'
        Invoke-Compose -Command @('run','--rm','--no-deps','--volume',$catalogMount,'api','python','-m',
            'app.commands.catalog','publish','/data/catalog/m08a-20261004/catalog.json')
        Write-Host 'Catalog published. Source DB unavailable: RAG remains unavailable until reviewed knowledge is imported.'
    }
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop is required.' }
    if ($Action -in @('Start','Stop','Daily')) {
        New-Item -ItemType Directory -Path $Private -Force | Out-Null
        $startupLock = [IO.File]::Open((Join-Path $Private 'startup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    }
    if ($Action -eq 'Stop') { Stop-Preview; exit 0 }
    if ($Action -eq 'Status') {
        $state = Get-State
        if ($state -and $state.localOnly) {
            Write-Host ('Local preview: '+$state.url)
            Invoke-Compose -Command @('ps')
        } elseif (Get-OwnedTunnel $state) { Write-Host ('Preview URL: '+$state.url) } else { Write-Host 'No active preview tunnel.' }
        exit 0
    }
    Invoke-Docker -Capture -Command @('info','--format','{{.OSType}}') | ForEach-Object {
        if ($_.Trim() -ne 'linux') { throw 'Switch Docker Desktop to Linux containers.' }
    }
    $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $LocalOnly -and $Action -in @('Start','Check') -and -not $cloudflared) { throw 'Install cloudflared first: winget install --id Cloudflare.cloudflared --exact' }
    if ($Action -eq 'Check') { Write-Host 'Required deployment tools are available.'; exit 0 }
    New-Item -ItemType Directory -Path $Private -Force | Out-Null
    if ($Action -eq 'Daily') { Invoke-Daily; exit 0 }
    # Startup, stop and maintenance share a lock to protect migrations and backups.
    $existing = Get-State
    $ownedTunnel = Get-OwnedTunnel $existing
    if ($ownedTunnel) {
        if ($LocalOnly) { Stop-Process -Id $ownedTunnel.Id -Force }
        else { Write-Host ('Already running: '+$existing.url); exit 0 }
    }
    $ownedPorts = Invoke-Docker -Capture -Command @('ps','--filter',('label=com.docker.compose.project='+$Project),
        '--filter','label=com.docker.compose.service=web','--format','{{.Ports}}')
    if ($ownedPorts -notmatch ('127\.0\.0\.1:'+$Port+'->')) {
        $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port)
        try { $listener.Start() } catch { throw "Local port $Port is occupied by another service. Use -Port with a free port." } finally { $listener.Stop() }
    }
    $source = Initialize-Preview
    if (-not $NoBuild) { Invoke-Compose -Ops -Command @('build','db','api','web','ops') }
    Invoke-Compose -Command @('up','-d','--wait','db')
    # Backup any existing preview before stopping the old single API and migrating.
    $schema = Invoke-Compose -Capture -Command @('exec','-T','db','psql','-U','postgres','-d','repair_guide_preview','-Atc',"SELECT to_regclass('public.alembic_version')")
    if ($schema.Trim()) {
        Invoke-Compose -Ops -Command @('run','--rm','--no-deps','ops','backup','--reviewed','/reviewed','--local','/backups','--remote','/remote')
    }
    Invoke-Compose -Command @('stop','api','web')
    Invoke-Compose -Admin -Command @('run','--rm','--no-deps','api','python','-m','alembic','upgrade','head')
    Copy-ReviewedData $source
    $url = 'https://localhost:' + $Port
    if (-not $LocalOnly) {
        $config = Join-Path $Private 'cloudflared.yml'
        [IO.File]::WriteAllText($config, "loglevel: info`n", $Utf8)
        $stdout = Join-Path $Private 'tunnel.out.log'
        $stderr = Join-Path $Private 'tunnel.err.log'
        $tunnel = Start-Process -FilePath $cloudflared.Source -ArgumentList @('--no-autoupdate','tunnel','--config',('"'+$config+'"'),
            '--protocol','http2','--url',('http://127.0.0.1:'+$Port)) -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $url = $null
        for ($attempt=0; $attempt -lt 90; $attempt++) {
            if ($tunnel.HasExited) { throw 'cloudflared exited. Check the private tunnel log.' }
            $log = (Read-TunnelLog $stderr) + (Read-TunnelLog $stdout)
            if ($log -match 'https://[a-z0-9-]+\.trycloudflare\.com') { $url=$Matches[0]; break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $url) { throw 'No tunnel URL received within 45 seconds.' }
    }
    $values = Read-Environment $EnvironmentPath
    $values['WEB_ORIGINS'] = '["'+$url+'"]'
    $values['PUBLIC_DOMAIN'] = ([Uri]$url).Host
    Write-Environment $values
    $state = @{processId=0; startTicks=''; localOnly=[bool]$LocalOnly; url=$url;
        startedAt=[DateTime]::UtcNow.ToString('o'); project=$Project; port=$Port}
    if ($tunnel) { $state.processId=$tunnel.Id; $state.startTicks=$tunnel.StartTime.ToUniversalTime().Ticks.ToString() }
    [IO.File]::WriteAllText($StatePath, ($state | ConvertTo-Json), $Utf8)
    Invoke-Compose -Command @('up','-d','--no-build','--wait')
    $readyJson = Invoke-Compose -Capture -Command @('exec','-T','api','python','-c',
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=10).read().decode())")
    $ready = $readyJson | ConvertFrom-Json
    if (-not $ready.catalogReady) { throw 'Published catalog is not ready.' }
    Invoke-Daily
    Write-Host ''
    Write-Host ('TEST DEPLOYMENT: '+$url) -ForegroundColor Green
    Write-Host ('RAG ready: '+$ready.ragReady+' | Isolated project: '+$Project)
    if ($LocalOnly) {
        Write-Host 'Local HTTPS only (self-signed test certificate). Stop with stop-test-deploy.bat.'
    } else {
        Write-Host 'The URL is public. Use test accounts only. Close with Ctrl+C or stop-test-deploy.bat.'
    }
    Write-Host 'Test deployment only: remote backup and production scheduling are not configured.'
    $startupLock.Dispose()
    $startupLock = $null
    if (-not $Detached -and -not $LocalOnly) {
        while (-not $tunnel.HasExited) { Start-Sleep -Seconds 2; $tunnel.Refresh() }
        throw 'Tunnel stopped. Run test-deploy.bat again for a new URL.'
    }
} catch {
    Write-Host ('FAILED: '+$_.Exception.Message) -ForegroundColor Red
    if ($tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    exit 1
} finally {
    if ($startupLock) { $startupLock.Dispose() }
    if ($Action -eq 'Start' -and -not $Detached -and $tunnel) {
        if (-not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
    }
}
