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

# --- Ensure daily litter exists today (force once if empty) ---
& $PyExe tools\sqlite_admin.py litter-run-now

$itemsTotal = sqlite3 "$env:GAME_STATE_ROOT\mutants.db" "SELECT COUNT(*) FROM items_instances WHERE origin='daily_litter';"
if (-not $itemsTotal -or $itemsTotal -eq "0") {
  & $PyExe tools\sqlite_admin.py litter-force-today
}

# --- Ensure monsters catalog import and initial spawn (idempotent) ---
$pyCheckMonstersCatalog = @"
import sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db)
cur = conn.cursor()
try:
    cur.execute('SELECT COUNT(*) FROM monsters_catalog')
    n = cur.fetchone()[0]
except sqlite3.OperationalError:
    n = -1
print(n)
"@
$tmpMonCatalog = [System.IO.Path]::GetTempFileName() + ".py"
$pyCheckMonstersCatalog | Set-Content -Path $tmpMonCatalog -Encoding UTF8
$getMonsterCatalogCount = {
  param($db)
  (& $PyExe $tmpMonCatalog $db).Trim()
}
$monsterCatalogCount = & $getMonsterCatalogCount $DBPath

if ((Test-Path "$StateDir\monsters\catalog.json") -and ($monsterCatalogCount -eq "0" -or $monsterCatalogCount -eq "-1")) {
  Write-Host "Importing monsters catalog into SQLite..."
  & $PyExe scripts\monsters_import.py --catalog "$StateDir\monsters\catalog.json" --db $DBPath
  if ($LASTEXITCODE -ne 0) {
    if (Test-Path $tmpMonCatalog) { Remove-Item $tmpMonCatalog -Force }
    Write-Error "Monster catalog import failed."
    exit 1
  }
  $monsterCatalogCount = & $getMonsterCatalogCount $DBPath
} else {
  Write-Host "Monsters catalog present (rows: $monsterCatalogCount)."
}

if (Test-Path $tmpMonCatalog) { Remove-Item $tmpMonCatalog -Force }

$pyCheckMonstersInstances = @"
import sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db)
cur = conn.cursor()
try:
    cur.execute('SELECT COUNT(*) FROM monsters_instances')
    n = cur.fetchone()[0]
except sqlite3.OperationalError:
    n = 0
print(n)
"@
$tmpMonInstances = [System.IO.Path]::GetTempFileName() + ".py"
$pyCheckMonstersInstances | Set-Content -Path $tmpMonInstances -Encoding UTF8
$monsterInstanceCount = (& $PyExe $tmpMonInstances $DBPath).Trim()

if ($monsterInstanceCount -eq "0") {
  $pyWorldYear = @"
import json, sys
from pathlib import Path
state_path = Path(sys.argv[1])
default_year = 2000
try:
    data = json.loads(state_path.read_text(encoding='utf-8'))
except Exception:
    print(default_year)
    sys.exit(0)
players = data.get('players') or []
year = None
for player in players:
    if player.get('is_active'):
        pos = player.get('pos') or []
        if isinstance(pos, list) and pos:
            try:
                year = int(pos[0])
            except (TypeError, ValueError):
                year = None
        if year is not None:
            break
if year is None:
    year = default_year
print(year)
"@
  $tmpYear = [System.IO.Path]::GetTempFileName() + ".py"
  $pyWorldYear | Set-Content -Path $tmpYear -Encoding UTF8
  $playerStatePath = Join-Path $StateDir "playerlivestate.json"
  $worldYearRaw = (& $PyExe $tmpYear $playerStatePath).Trim()
  Remove-Item $tmpYear -Force
  if (-not $worldYearRaw) { $worldYearRaw = "2000" }
  $worldYear = [int]$worldYearRaw
  Write-Host "Spawning initial monsters for year $worldYear..."
  & $PyExe scripts\monsters_initial_spawn.py --db $DBPath --year $worldYear --per-monster 4
  if ($LASTEXITCODE -ne 0) {
    if (Test-Path $tmpMonInstances) { Remove-Item $tmpMonInstances -Force }
    Write-Error "Initial monster spawn failed."
    exit 1
  }
} else {
  Write-Host "Monsters already present (rows: $monsterInstanceCount)."
}

if (Test-Path $tmpMonInstances) { Remove-Item $tmpMonInstances -Force }

# --- Launch the game ---
Write-Host ""
Write-Host "Launching game (SQLite backend)..."
& $PyExe -m mutants
