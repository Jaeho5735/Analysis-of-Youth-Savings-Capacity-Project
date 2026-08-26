# cleanup_project.ps1
# Tidy the project root: remove one-off logs, move stray scripts, drop build junk.
# Comments are ASCII on purpose: Windows PowerShell 5 reads .ps1 as CP949 and
# mangles UTF-8 Korean, which breaks parsing.
#
#   .\cleanup_project.ps1          # dry run - prints what it would do
#   .\cleanup_project.ps1 -Apply   # actually do it

param([switch]$Apply)

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Act($desc, $block) {
    if ($Apply) {
        & $block
        Write-Host "  [done] $desc" -ForegroundColor Green
    } else {
        Write-Host "  [plan] $desc" -ForegroundColor Yellow
    }
}

# 1. One-off run logs. These are outputs, not code.
Step "Remove run logs and temp files"
foreach ($f in @("analysis_result.txt", "csv_headers.txt", "qc_result.txt", "tree.txt")) {
    if (Test-Path $f) { Act "delete $f" { Remove-Item -LiteralPath $f -Force } }
}
Get-ChildItem -Filter "*.lnk" -File -EA SilentlyContinue | ForEach-Object {
    $p = $_.FullName
    Act "delete shortcut $($_.Name)" { Remove-Item -LiteralPath $p -Force }
}

# 2. Local editor settings.
Step "Remove local settings"
if (Test-Path ".claude") { Act "delete .claude/" { Remove-Item -Recurse -Force ".claude" } }

# 3. Stray scripts in root -> proper folders.
#    Pipeline re-run scripts go to src/pipeline, one-off probes to scripts/.
Step "Move root scripts"
$pipeline = @("rebuild_analysis_ready.py", "rebuild_commute_burden.py",
              "requery_commute_routes.py", "reselect_routes.py")
if ($pipeline | Where-Object { Test-Path $_ }) {
    Act "mkdir src\pipeline" { New-Item -ItemType Directory -Force "src\pipeline" | Out-Null }
}
foreach ($f in $pipeline) {
    if (Test-Path $f) { Act "move $f -> src\pipeline\" { Move-Item -LiteralPath $f "src\pipeline" -Force } }
}
# Korean filenames can break on GitHub/CI, so rename to ASCII.
$night = "$([char]0xC9C4)$([char]0xB2E8)_$([char]0xC2EC)$([char]0xC57C)$([char]0xBC84)$([char]0xC2A4).py"
if (Test-Path $night) {
    Act "mkdir scripts" { New-Item -ItemType Directory -Force "scripts" | Out-Null }
    Act "move $night -> scripts\diagnose_night_bus.py" {
        Move-Item -LiteralPath $night "scripts\diagnose_night_bus.py" -Force
    }
}

# 4. web leftovers: debug screenshots, preview mockups, preview tooling.
Step "Remove web leftovers"
foreach ($d in @("web\scratch", "web\tools")) {
    if (Test-Path $d) { Act "delete $d" { Remove-Item -Recurse -Force $d } }
}
Get-ChildItem "web" -Filter "preview*.html" -File -EA SilentlyContinue | ForEach-Object {
    $p = $_.FullName
    Act "delete web\$($_.Name)" { Remove-Item -LiteralPath $p -Force }
}
if (Test-Path "web\apply_json_fixes.py") {
    Act "delete web\apply_json_fixes.py" { Remove-Item -LiteralPath "web\apply_json_fixes.py" -Force }
}

# 5. Backup copies.
Step "Remove backup files"
Get-ChildItem -Recurse -Include "*.bak", "*.bak.csv", "*.json.bak" -File -EA SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\(\.venv|\.git)\\' } | ForEach-Object {
        $p = $_.FullName
        $rel = $p.Replace($PWD.Path + "\", "")
        Act "delete $rel" { Remove-Item -LiteralPath $p -Force }
    }

# 6. Compress API caches. Raw JSON is ~7MB and contains addresses.
Step "Compress API caches"
foreach ($n in @("kakao_cache", "jibun_cache")) {
    $j = "data\$n.json"
    if ((Test-Path $j) -and -not (Test-Path "$j.gz")) {
        Act "gzip $j" {
            python -c "import gzip,shutil,sys;shutil.copyfileobj(open(sys.argv[1],'rb'),gzip.open(sys.argv[1]+'.gz','wb'))" $j
        }
    }
}

# 7. Drop big/quarantine files from the git index (files stay on disk).
Step "Untrack large files in git"
foreach ($f in @("data/commute_routes_analysis_ready.csv",
                 "data/kakao_cache.json", "data/jibun_cache.json")) {
    Act "git rm --cached $f" { git rm --cached --quiet -- $f 2>$null }
}
Act "git rm --cached -r data/quarantine" { git rm --cached -r --quiet -- "data/quarantine" 2>$null }

Write-Host ""
if ($Apply) {
    Step "Done"
    Write-Host "  Next: git add -A ; git status --short"
} else {
    Step "Dry run only"
    Write-Host "  To apply: .\cleanup_project.ps1 -Apply" -ForegroundColor Yellow
}