# ============================================================
#  Start AI Workspace
#  1. เปิด LM Studio + Start Server
#  2. SSH เข้า NAS แล้ว restart hybrid-ai
# ============================================================

$LMStudioPath = "$env:LOCALAPPDATA\Programs\LM-Studio\LM Studio.exe"
$NAS_HOST     = "192.168.51.49"
$NAS_USER     = "pawin"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Workspace Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ---------- 1. เปิด LM Studio ----------
if (Test-Path $LMStudioPath) {
    Write-Host "`n[1/3] เปิด LM Studio..." -ForegroundColor Yellow
    Start-Process $LMStudioPath
    Write-Host "      รอ LM Studio โหลด 8 วินาที..." -ForegroundColor Gray
    Start-Sleep -Seconds 8
} else {
    Write-Host "`n[1/3] ไม่พบ LM Studio ที่ $LMStudioPath" -ForegroundColor Red
    Write-Host "      กรุณาเปิด LM Studio และ Start Server ด้วยตัวเองค่ะ" -ForegroundColor Red
}

# ---------- 2. Start LM Studio Server (ถ้ามี CLI) ----------
$lmsCLI = "$env:LOCALAPPDATA\Programs\LM-Studio\resources\app\bin\lms.exe"
if (Test-Path $lmsCLI) {
    Write-Host "`n[2/3] Start LM Studio Server..." -ForegroundColor Yellow
    Start-Process $lmsCLI -ArgumentList "server start" -NoNewWindow -Wait
    Write-Host "      Server started!" -ForegroundColor Green
} else {
    Write-Host "`n[2/3] กรุณากด 'Start Server' ใน LM Studio ด้วยตัวเองค่ะ" -ForegroundColor Yellow
    Write-Host "      (รอ 15 วินาทีก่อนไปขั้นตอนต่อไป...)" -ForegroundColor Gray
    Start-Sleep -Seconds 15
}

# ---------- 3. SSH เข้า NAS restart Docker ----------
Write-Host "`n[3/3] Restart hybrid-ai บน NAS..." -ForegroundColor Yellow
Write-Host "      (จะถามรหัสผ่าน NAS ค่ะ)" -ForegroundColor Gray
ssh "${NAS_USER}@${NAS_HOST}" "sudo docker restart hybrid-ai && echo 'hybrid-ai restarted OK'"

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  เสร็จแล้ว! เปิด https://ai.pawinhome.com" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

Start-Process "https://ai.pawinhome.com"

Write-Host "`nกด Enter เพื่อปิดหน้าต่างนี้..."
Read-Host
