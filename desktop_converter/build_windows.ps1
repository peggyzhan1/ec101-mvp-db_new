$ErrorActionPreference = "Stop"
python -m pip install -r "$PSScriptRoot/requirements.txt"
pyinstaller --noconfirm --clean --windowed --name EC101StandardConverter --paths "$PSScriptRoot/.." "$PSScriptRoot/app.py"
Write-Host "Build complete: dist/EC101StandardConverter/EC101StandardConverter.exe"
