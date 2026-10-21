# 停止 Aligo 演示服务（只杀占用 3003 端口的那个进程）
$port = 3003
$conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $conn) {
    Write-Host "[i] 3003 端口没有在监听，服务已停止。" -ForegroundColor Yellow
    exit 0
}
foreach ($c in $conn) {
    $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($p) {
        Write-Host ("[..] 停止 PID {0} ({1})" -f $p.Id, $p.ProcessName) -ForegroundColor Yellow
        Stop-Process -Id $p.Id -Force
    }
}
Start-Sleep -Seconds 1
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "[X] 端口仍被占用，请手动检查。" -ForegroundColor Red
} else {
    Write-Host "[OK] 已停止。" -ForegroundColor Green
}