param(
    [ValidatePattern('^[a-z0-9_]+$')]
    [string]$Series = 'forward_paper_v2'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statusPath = Join-Path $projectRoot "results\$Series\watch_status.json"
$watchState = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$watchPid = [int]$watchState.pid
$osProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $watchPid"
$checked = [DateTimeOffset]::UtcNow
$age = $checked.ToUnixTimeMilliseconds() - [long]$watchState.heartbeat_ms
$running = $false
$creationMatches = $false
if ($null -ne $osProcess) {
    $created = [DateTimeOffset]$osProcess.CreationDate.ToUniversalTime()
    $creationMatches = [Math]::Abs($created.ToUnixTimeMilliseconds() - [long]$watchState.started_ms) -lt 10000
    $running = $creationMatches -and $age -ge 0 -and $age -lt 30000 -and
        $osProcess.CommandLine.Contains("-m jev_trader.forward_watch --series $Series --hours ") -and
        @('starting', 'acquiring', 'observed', 'waiting', 'retry_wait').Contains([string]$watchState.phase)
}
$sourcePath = Join-Path $projectRoot 'src\jev_trader\forward_watch.py'
$sourceMatches = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -eq $watchState.watcher_source_sha256
$checkpoint = [ordered]@{
    checked_utc = $checked.ToString('o')
    supervisor_running_verified = ($running -and $sourceMatches)
    heartbeat_age_ms = $age
    creation_matches_run = $creationMatches
    source_hash_matches = $sourceMatches
    os_process = $(if ($null -ne $osProcess) {
        [ordered]@{
            pid = $osProcess.ProcessId
            parent_pid = $osProcess.ParentProcessId
            created_utc = $created.ToString('o')
            executable = $osProcess.ExecutablePath
            command_line = $osProcess.CommandLine
        }
    } else { $null })
    status = $watchState
    limits = @('Point-in-time OS verification only.', 'No profit or trade execution is inferred from a live process.')
}
$destination = Join-Path $projectRoot ("docs\forward_watch_status_" + $checked.ToString('yyyy-MM-dd') + '.json')
[System.IO.File]::WriteAllText($destination, ($checkpoint | ConvertTo-Json -Depth 20) + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false))
$checkpoint | ConvertTo-Json -Depth 20
if (-not $checkpoint.supervisor_running_verified) {
    exit 1
}
