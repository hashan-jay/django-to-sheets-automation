$server = "D:\Redis\redis-server.exe"
$conf = "D:\Redis\redis.windows-service.conf"
if (-not (Test-Path $server)) {
    Write-Host "Redis server was not found at $server"
    exit 1
}
$listening = Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "Redis is already running."
    exit 0
}
$service = Get-Service -Name "Redis" -ErrorAction SilentlyContinue
if ($service) {
    if ($service.Status -ne "Running") {
        Start-Service -Name "Redis"
    }
} else {
    & $server --service-install $conf --service-name Redis
    & $server --service-start --service-name Redis
}
Start-Sleep -Seconds 1
$listening = Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host "Redis is running."
    exit 0
}
Start-Process -FilePath $server -ArgumentList $conf -WorkingDirectory "D:\Redis" -WindowStyle Hidden
Start-Sleep -Seconds 1
Write-Host "Redis was started."
