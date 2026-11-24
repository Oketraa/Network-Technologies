param([ValidateRange(1, 65535)][int]$Port = 8000)

$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$mailpitPath = Join-Path $project '.tools/mailpit.exe'
$smtpPort = if ($env:ROBOTAXI_SMTP_PORT) { [int]$env:ROBOTAXI_SMTP_PORT } else { 1025 }
$inboxPort = if ($env:ROBOTAXI_INBOX_PORT) { [int]$env:ROBOTAXI_INBOX_PORT } else { 8025 }

if (-not (Test-Path -LiteralPath $mailpitPath)) {
    $installed = Get-Command mailpit -ErrorAction SilentlyContinue
    if ($installed) {
        $mailpitPath = $installed.Source
    } else {
        $mailpitArchive = Join-Path ([IO.Path]::GetTempPath()) ('robotaxi-mailpit-' + [Guid]::NewGuid().ToString('N') + '.zip')
        $machineArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
        $platform = switch ($machineArchitecture) {
            'X64' { 'amd64' }
            'Arm64' { 'arm64' }
            default { throw "Mailpit requires Windows x64 or ARM64. Architecture: $machineArchitecture" }
        }
        try {
            $download = "https://github.com/axllent/mailpit/releases/latest/download/mailpit-windows-$platform.zip"
            Invoke-WebRequest -Uri $download -OutFile $mailpitArchive -TimeoutSec 60
            Expand-Archive -LiteralPath $mailpitArchive -DestinationPath (Split-Path -Parent $mailpitPath) -Force
        } finally {
            if (Test-Path -LiteralPath $mailpitArchive) {
                Remove-Item -LiteralPath $mailpitArchive
            }
        }
    }
}

$inbox = Start-Process -FilePath $mailpitPath -WorkingDirectory $project -WindowStyle Hidden -PassThru -ArgumentList @(
    '--smtp', "127.0.0.1:${smtpPort}", '--listen', "127.0.0.1:${inboxPort}",
    '--allowed-hosts', '127.0.0.1,localhost', '--disable-version-check', '--max-age', '1h', '--max', '100'
)
try {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($inbox.HasExited) { throw 'Mailpit could not start. Check whether the SMTP or inbox port is in use.' }
        $probe = [Net.Sockets.TcpClient]::new()
        try {
            $probe.Connect('127.0.0.1', $smtpPort)
            break
        } catch {
            if ($attempt -eq 29) { throw }
            Start-Sleep -Milliseconds 100
        } finally {
            $probe.Dispose()
        }
    }
    Write-Host "Mailpit: http://127.0.0.1:$inboxPort/"
    & python (Join-Path $project 'main.py') --port $Port
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
} finally {
    if (-not $inbox.HasExited) { Stop-Process -InputObject $inbox }
}
