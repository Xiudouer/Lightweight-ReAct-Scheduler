$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    python -m PyInstaller --noconfirm --onedir --contents-directory runtime --name LiteReAct --paths . --distpath build/dist --workpath build/work --specpath build run.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    Write-Output 'Executable is in build/dist/LiteReAct/. Keep runtime/ beside the EXE.'
} finally {
    Pop-Location
}
