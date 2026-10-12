param(
    [string]$Python = "python",
    [string]$DistPath = "dist",
    [string]$WorkPath = "build"
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedPython = if (Test-Path -LiteralPath $Python) { (Resolve-Path -LiteralPath $Python).Path } else { $Python }
Push-Location -LiteralPath $repoRoot
try {
    & $resolvedPython "$PSScriptRoot/collect_notices.py" "$repoRoot/reference/licenses"
    if ($LASTEXITCODE -ne 0) { throw "Dependency notice collection failed" }
    & $resolvedPython -m PyInstaller --noconfirm --clean --windowed --onedir --name LegionGoBar `
        --paths "$repoRoot/src" --distpath $DistPath --workpath $WorkPath --specpath $WorkPath `
        --add-data "$repoRoot/src/legiongobar/assets/reference.json;legiongobar/assets" `
        --add-data "$repoRoot/src/legiongobar/locales;legiongobar/locales" `
        --add-data "$repoRoot/src/legiongobar/assets/theme.qss;legiongobar/assets" `
        --add-data "$repoRoot/src/legiongobar/assets/glyphs;legiongobar/assets/glyphs" `
        --add-data "$repoRoot/src/legiongobar/assets/ui;legiongobar/assets/ui" `
        --add-data "$repoRoot/src/legiongobar/assets/fonts;legiongobar/assets/fonts" `
        --add-binary "$repoRoot/src/legiongobar/assets/native/ADLXCSharpBind.dll;legiongobar/assets/native" `
        --add-data "$repoRoot/reference;reference" --add-data "$repoRoot/THIRD-PARTY-NOTICES.md;." --add-data "$repoRoot/LICENSE;." "$repoRoot/tools/entrypoint.py"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    & $resolvedPython "$PSScriptRoot/fix_qt_runtime.py" (Join-Path $DistPath "LegionGoBar")
    if ($LASTEXITCODE -ne 0) { throw "Qt runtime verification failed" }
    Copy-Item -LiteralPath README.md -Destination (Join-Path $DistPath "LegionGoBar/README.md")
    $docOutput = Join-Path $DistPath "LegionGoBar/docs"
    New-Item -ItemType Directory -Force -Path $docOutput | Out-Null
    Copy-Item -Path "$repoRoot/docs/*" -Destination $docOutput -Recurse -Force
    '@echo off
"%~dp0LegionGoBar.exe" --demo
' | Set-Content -LiteralPath (Join-Path $DistPath "LegionGoBar/Preview.cmd") -Encoding ascii
} finally {
    Pop-Location
}
