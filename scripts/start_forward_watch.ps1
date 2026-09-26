param(
    [ValidatePattern('^[a-z0-9_]+$')]
    [string]$Series = 'forward_paper_v2',
    [ValidateRange(0.001, 72)]
    [double]$Hours = 72
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$seriesRoot = Join-Path $projectRoot "results\$Series"
if (-not (Test-Path -LiteralPath (Join-Path $seriesRoot 'ledger.jsonl'))) {
    throw 'Initialize the explicit paper series before starting a watcher.'
}
foreach ($control in @('watch.lock', 'watch.stop')) {
    if (Test-Path -LiteralPath (Join-Path $seriesRoot $control)) {
        throw "Existing $control requires review; nothing was removed."
    }
}
$runStamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')
$arguments = @('-m', 'jev_trader.forward_watch', '--series', $Series, '--hours',
    $Hours.ToString([System.Globalization.CultureInfo]::InvariantCulture))
$process = Start-Process -FilePath (Join-Path $projectRoot '.venv\Scripts\python.exe') `
    -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $seriesRoot "watch-$runStamp.stdout.log") `
    -RedirectStandardError (Join-Path $seriesRoot "watch-$runStamp.stderr.log") -PassThru
[pscustomobject]@{
    LauncherPid = $process.Id
    Series = $Series
    MaxHours = $Hours
    StatusPath = (Join-Path $seriesRoot 'watch_status.json')
    Note = 'Verify the heartbeat PID and OS command line; launcher creation alone is not readiness.'
} | ConvertTo-Json
