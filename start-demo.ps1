# Aligo 面试演示 · 一键启动
# 用法：右键“使用 PowerShell 运行”，或在本目录执行  .\start-demo.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$port   = 3003
$url    = "http://127.0.0.1:$port/"
$health = "http://127.0.0.1:$port/api/health"

function Test-Up {
    try {
        $r = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  Aligo 智能旅行助手 · 演示启动器" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

# 1) 已经跑起来了就直接开浏览器
if (Test-Up) {
    Write-Host "[OK] 服务已在运行：$url" -ForegroundColor Green
    Start-Process $url
    exit 0
}

# 2) 检查 Python 虚拟环境
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "[X] 找不到 .venv，请先执行：" -ForegroundColor Red
    Write-Host "    python -m venv .venv --system-site-packages"
    Write-Host "    .\.venv\Scripts\python.exe -m pip install agentscope==1.0.16"
    exit 1
}

# 3) 检查向量库（Milvus Lite 的落盘目录）
$dbRoot = Join-Path $env:USERPROFILE '.aligo\milvus_data\milvus_lite.db'
$dbFile = Get-ChildItem -Path $dbRoot -Recurse -Filter '*.parquet' -ErrorAction SilentlyContinue
if (-not $dbFile) {
    Write-Host "[!] 未检测到向量数据，正在构建知识库（约 30 秒）..." -ForegroundColor Yellow
    & $py '.claude\skills\ask-question\script\init_knowledge_base.py'
    if ($LASTEXITCODE -ne 0) { Write-Host "[X] 知识库构建失败" -ForegroundColor Red; exit 1 }
} else {
    $kb = Get-ChildItem -Path $dbRoot -Recurse -Filter '*.parquet' |
          Where-Object { $_.FullName -match 'business_travel_knowledge' } |
          Measure-Object -Property Length -Sum
    Write-Host ("[OK] 向量库就绪：{0} 个数据文件 / {1:N0} KB" -f $kb.Count, ($kb.Sum / 1KB)) -ForegroundColor Green
}

# 4) 起服务（独立窗口，关掉这个窗口也不影响）
Write-Host "[..] 启动后端 + 前端（同一个 3003 端口）..." -ForegroundColor Yellow
Start-Process -FilePath $py `
    -ArgumentList '-m','uvicorn','server.app:app','--host','127.0.0.1','--port',"$port" `
    -WorkingDirectory $root `
    -WindowStyle Minimized

# 5) 等健康检查通过（首次要加载 embedding 模型，约 10-20 秒）
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 800
    if (Test-Up) { $ok = $true; break }
}

if ($ok) {
    Write-Host ""
    Write-Host "[OK] 启动成功：$url" -ForegroundColor Green
    Write-Host "     健康检查：$health" -ForegroundColor DarkGray
    Write-Host "     停止服务：.\stop-demo.ps1" -ForegroundColor DarkGray
    Start-Process $url
} else {
    Write-Host "[X] 60 秒内没起来，看 logs\server.log 最后几行：" -ForegroundColor Red
    if (Test-Path (Join-Path $root 'logs\server.log')) {
        Get-Content (Join-Path $root 'logs\server.log') -Tail 20
    }
    exit 1
}