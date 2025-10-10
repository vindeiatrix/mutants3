<#  Run-Mutants.ps1  — run from anywhere; script assumes it lives in repo root.
    Usage (first time or any time):
      powershell -ExecutionPolicy Bypass -File C:\mutants3-main\Run-Mutants.ps1
#>

$ErrorActionPreference = "Stop"

# --- Locate repo root (the folder containing this script) ---
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo

# --- Paths & env for this session ---
$StateDir = Join-Path $Repo "state"
$VenvDir  = Join-Path $Repo ".venv"
$PyExe    = Join-Path $VenvDir "Scripts\python.exe"
$PipExe   = Join-Path $VenvDir "Scripts\pip.exe"
$DBPath   = Join-Path $StateDir "mutants.db"

if (!(Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir | Out-Null }
if (!(Test-Path $DBPath)) {
  Write-Host "Creating SQLite database file..."
  New-Item -ItemType File -Path $DBPath | Out-Null
}

$env:MUTANTS_STATE_BACKEND = "sqlite"
$env:GAME_STATE_ROOT = $StateDir

Write-Host "Repo: $Repo"
Write-Host "DB:   $DBPath"
Write-Host "ENV:  MUTANTS_STATE_BACKEND=$($env:MUTANTS_STATE_BACKEND); GAME_STATE_ROOT=$($env:GAME_STATE_ROOT)"

# --- Ensure Python venv exists & project is installed editable ---
if (!(Test-Path $PyExe)) {
  Write-Host "Creating virtual environment..."
  py -m venv $VenvDir
}
# upgrade pip quietly; install project (safe to re-run)
& $PyExe -m pip install --upgrade pip > $null
& $PipExe install -e $Repo

# --- Ensure DB exists and is on latest schema (idempotent) ---
& $PyExe tools\sqlite_admin.py init

# --- Import ITEMS catalog into SQLite if empty (idempotent) ---
$pyCheckCatalog = @"
import os, sqlite3, json, sys
root = os.environ['GAME_STATE_ROOT']; db = os.path.join(root,'mutants.db')
conn = sqlite3.connect(db); cur = conn.cursor()
try:
    cur.execute('SELECT COUNT(*) FROM items_catalog'); n = cur.fetchone()[0]
except sqlite3.OperationalError:
    n = -1
print(n)
"@
$tmp1 = [System.IO.Path]::GetTempFileName() + ".py"
$pyCheckCatalog | Set-Content -Path $tmp1 -Encoding UTF8
$catalogCount = (& $PyExe $tmp1).Trim()
Remove-Item $tmp1 -Force

if ($catalogCount -eq "0" -and (Test-Path "$StateDir\items\catalog.json")) {
  Write-Host "Importing items catalog into SQLite..."
  & $PyExe tools\sqlite_admin.py catalog-import-items
} else {
  Write-Host "Items catalog present (rows: $catalogCount)."
}

# --- Ensure monsters catalog + initial spawn (idempotent) ---
Write-Host "Ensuring monsters catalog and initial spawn..."
& $PyExe tools\bootstrap_monsters.py --database $DBPath

# --- Ensure daily litter exists today (force once if empty) ---
& $PyExe tools\sqlite_admin.py litter-run-now

$itemsTotal = sqlite3 "$env:GAME_STATE_ROOT\mutants.db" "SELECT COUNT(*) FROM items_instances WHERE origin='daily_litter';"
if (-not $itemsTotal -or $itemsTotal -eq "0") {
  & $PyExe tools\sqlite_admin.py litter-force-today
}

# --- Launch the game ---
Write-Host ""
Write-Host "Launching game (SQLite backend)..."
& $PyExe -m mutants
