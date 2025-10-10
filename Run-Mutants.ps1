<#  Run-Mutants.ps1  — run from anywhere; script assumes it lives in repo root.
    Usage (first time or any time):
      powershell -ExecutionPolicy Bypass -File C:\mutants3-main\Run-Mutants.ps1
#>

param(
    [string]$Years
)

$ErrorActionPreference = "Stop"

# --- Locate repo root (the folder containing this script) ---
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo
Unblock-File -Path "$PSScriptRoot\Run-Mutants.ps1" -ErrorAction SilentlyContinue

# --- Paths & env for this session ---
$StateDir = Join-Path $Repo "state"
$VenvDir  = Join-Path $Repo ".venv"
$PyExe    = Join-Path $VenvDir "Scripts\python.exe"
$PipExe   = Join-Path $VenvDir "Scripts\pip.exe"
$DBPath   = Join-Path $StateDir "mutants.db"

function Invoke-SqlScalar([string]$dbPath, [string]$sql) {
  $out = & $PyExe "$PSScriptRoot\tools\sqlite_eval.py" --db $dbPath --scalar $sql
  if ($LASTEXITCODE -ne 0) { throw "Invoke-SqlScalar failed: $sql" }
  return [int]("$out" -replace '\s+$','')
}

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
try {
  $catalogCount = Invoke-SqlScalar $DBPath "SELECT COUNT(*) FROM items_catalog"
} catch {
  $catalogCount = -1
}

if ($catalogCount -eq 0 -and (Test-Path "$StateDir\items\catalog.json")) {
  Write-Host "Importing items catalog into SQLite..."
  & $PyExe tools\sqlite_admin.py catalog-import-items
} else {
  Write-Host "Items catalog present (rows: $catalogCount)."
}

# --- Ensure daily litter exists today (force once if empty) ---
& $PyExe tools\sqlite_admin.py litter-run-now

$itemsTotal = Invoke-SqlScalar $DBPath "SELECT COUNT(*) FROM items_instances WHERE origin='daily_litter'"
if (-not $itemsTotal -or $itemsTotal -eq 0) {
  & $PyExe tools\sqlite_admin.py litter-force-today
}

# --- Ensure monsters catalog import and initial spawn (idempotent) ---
try {
  $monsterCatalogCount = Invoke-SqlScalar $DBPath "SELECT COUNT(*) FROM monsters_catalog"
} catch {
  $monsterCatalogCount = -1
}

if ((Test-Path "$StateDir\monsters\catalog.json") -and ($monsterCatalogCount -eq 0 -or $monsterCatalogCount -eq -1)) {
  Write-Host "Importing monsters catalog into SQLite..."
  & $PyExe scripts\monsters_import.py --catalog "$StateDir\monsters\catalog.json" --db $DBPath
  if ($LASTEXITCODE -ne 0) {
    Write-Error "Monster catalog import failed."
    exit 1
  }
  try {
    $monsterCatalogCount = Invoke-SqlScalar $DBPath "SELECT COUNT(*) FROM monsters_catalog"
  } catch {
    $monsterCatalogCount = -1
  }
} else {
  Write-Host "Monsters catalog present (rows: $monsterCatalogCount)."
}

try {
  $monsterInstanceCount = Invoke-SqlScalar $DBPath "SELECT COUNT(*) FROM monsters_instances"
} catch {
  $monsterInstanceCount = 0
}
Write-Host "Monsters currently present (rows: $monsterInstanceCount)."

$spawnArgs = @("--db", $DBPath, "--per-monster", "4")
if ($Years) {
  Write-Host "Overriding spawn years: $Years"
  $spawnArgs += @("--years", $Years)
}

Write-Host "Ensuring passive monsters are topped up across all world years..."
& $PyExe "scripts\monsters_initial_spawn.py" @spawnArgs
if ($LASTEXITCODE -ne 0) {
  Write-Error "Monster spawn top-up failed."
  exit 1
}

# --- Launch the game ---
Write-Host ""
Write-Host "Launching game (SQLite backend)..."
& $PyExe -m mutants
