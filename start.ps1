# ============================================================
# Hybrid AI Workspace — Start Script (Windows PowerShell)
# ============================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "🧠 Hybrid AI Workspace" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan

# --- 1. หา Python ---
$PythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $PythonCmd = $cmd
            Write-Host "✅ พบ $ver ($cmd)" -ForegroundColor Green
            break
        }
    } catch { }
}
if (-not $PythonCmd) {
    Write-Host "❌ ไม่พบ Python 3 — ดาวน์โหลดที่ https://www.python.org/downloads/" -ForegroundColor Red
    Read-Host "กด Enter เพื่อออก"
    exit 1
}

# --- 2. Virtual Environment ---
$VenvPath = Join-Path $ScriptDir ".venv"
$VenvActivate = Join-Path $VenvPath "Scripts\Activate.ps1"

if (-not (Test-Path $VenvPath)) {
    Write-Host "📦 สร้าง Virtual Environment..." -ForegroundColor Yellow
    & $PythonCmd -m venv .venv
}

Write-Host "🔧 เปิดใช้ Virtual Environment..." -ForegroundColor Yellow
& $VenvActivate

# --- 3. ติดตั้ง dependencies ---
Write-Host "📚 ตรวจสอบ dependencies..." -ForegroundColor Yellow
& python -m pip install -r requirements.txt -q --disable-pip-version-check

# --- 4. ตรวจสอบ .env ---
if (-not (Test-Path ".env")) {
    Write-Host "⚠️  ไม่พบ .env — สร้างจาก template..." -ForegroundColor Yellow
    @"
# Ollama (Local LLM)
OLLAMA_BASE_URL=http://192.168.51.235:11434/v1
OLLAMA_MODEL=llama3

# Gemini (Cloud LLM)
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

# ChromaDB (Long-term Memory)
CHROMA_HOST=192.168.51.49
CHROMA_PORT=8000
"@ | Out-File -FilePath ".env" -Encoding UTF8
    Write-Host "✅ สร้าง .env แล้ว — แก้ค่าใน .env ก่อนใช้งาน" -ForegroundColor Green
}

# --- 5. รัน Streamlit ---
Write-Host ""
Write-Host "🚀 กำลังเปิด Hybrid AI Workspace..." -ForegroundColor Green
Write-Host "   เปิด Browser: http://localhost:8501" -ForegroundColor Cyan
Write-Host "   กด Ctrl+C เพื่อหยุด" -ForegroundColor Gray
Write-Host ""

python -m streamlit run app.py --server.port 8501 --server.headless false
