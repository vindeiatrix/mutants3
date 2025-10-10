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

# --- Ensure daily litter exists today (force once if empty) ---
$pyEnsureLitter = @"
import os, sqlite3, time, logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
from datetime import date
root = os.environ['GAME_STATE_ROOT']; db = os.path.join(root,'mutants.db')
conn = sqlite3.connect(db); cur = conn.cursor()
def count_items():
    cur.execute('SELECT COUNT(*) FROM items_instances'); return cur.fetchone()[0]
def get_stamp():
    cur.execute("SELECT value FROM runtime_kv WHERE key='daily_litter_date'"); row = cur.fetchone()
    return row[0] if row else None

items_before = count_items()
stamp = get_stamp()

# Try to run the daily litter pass if your code exposes it.
ran = False
try:
    from mutants.bootstrap.daily_litter import run_daily_litter
    run_daily_litter()  # should be idempotent if today already done
    ran = True
except Exception as e:
    logging.warning("daily_litter hook not callable yet (%s); will fallback if needed.", e)

# If still empty, force one pass by clearing today's stamp and trying again.
items_mid = count_items()
if items_mid == 0:
    cur.execute("DELETE FROM items_instances WHERE origin='daily_litter'")
    cur.execute("DELETE FROM runtime_kv WHERE key='daily_litter_date'")
    conn.commit()
    try:
        from mutants.bootstrap.daily_litter import run_daily_litter
        run_daily_litter()
        ran = True
    except Exception:
        pass

print("RAN=" + ("1" if ran else "0"))
print("COUNT=" + str(count_items()))
"@
$tmp2 = [System.IO.Path]::GetTempFileName() + ".py"
$pyEnsureLitter | Set-Content -Path $tmp2 -Encoding UTF8
$ensureOut = & $PyExe $tmp2
Remove-Item $tmp2 -Force

# Parse results
$ran     = ($ensureOut | Select-String -Pattern "^RAN=(\d+)$").Matches.Groups[1].Value
$itemCnt = ($ensureOut | Select-String -Pattern "^COUNT=(\d+)$").Matches.Groups[1].Value
if (!$itemCnt) { $itemCnt = "0" }
Write-Host "Daily litter ensured (ran:$ran) — items in DB: $itemCnt"

# --- Launch the game ---
Write-Host ""
Write-Host "Launching game (SQLite backend)..."
& $PyExe -m mutants
