param(
    [string]$CaBundle
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$seriesRoot = Join-Path $projectRoot 'results\minute_jev_paper_20260927'
foreach ($control in @('watch.lock', 'watch.stop')) {
    if (Test-Path -LiteralPath (Join-Path $seriesRoot $control)) {
        throw "Existing $control requires review; nothing was removed."
    }
}
New-Item -ItemType Directory -Path $seriesRoot -Force | Out-Null
$runStamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')
$arguments = @('-m', 'jev_trader.minute_jev_paper', '--hours', '72')
if ($CaBundle) {
    $resolvedCaBundle = (Resolve-Path -LiteralPath $CaBundle).Path
    $arguments += @('--ca-bundle', $resolvedCaBundle)
}
$process = Start-Process -FilePath (Join-Path $projectRoot '.venv\Scripts\python.exe') `
    -ArgumentList $arguments `
    -WorkingDirectory $projectRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $seriesRoot "watch-$runStamp.stdout.log") `
    -RedirectStandardError (Join-Path $seriesRoot "watch-$runStamp.stderr.log") -PassThru
[pscustomobject]@{
    LauncherPid = $process.Id
    Series = 'minute_jev_paper_20260927'
    MaxHours = 72
    StatusPath = (Join-Path $seriesRoot 'status.json')
    Note = 'Verify heartbeat after startup; TLS certificate validation must remain enabled.'
} | ConvertTo-Json
