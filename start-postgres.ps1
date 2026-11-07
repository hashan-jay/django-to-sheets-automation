$ctl = "D:\PostgreSQL\17\pgsql\bin\pg_ctl.exe"
$data = "D:\PostgreSQL\17\data"
$log = "D:\PostgreSQL\17\postgres.log"
& $ctl -D $data status
if ($LASTEXITCODE -eq 0) {
    Write-Host "PostgreSQL is already running."
    exit 0
}
& $ctl -D $data -l $log start
