# Voice Cloner - CPU-only installation (Windows, Python 3.11)
# Place beside manage.py and requirements.txt, then run:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install_cpu_python311.ps1
#
# Prerequisites: Windows x64 and 64-bit Python 3.11 + Python Launcher (py).
# This version deliberately uses CPU-only PyTorch. It does not install CUDA,
# ROCm, or TorchCodec (Coqui only requires TorchCodec with PyTorch 2.9+).

$ErrorActionPreference = 'Stop'
$ProjectDir = $PSScriptRoot
$RequirementsPath = Join-Path $ProjectDir 'requirements.txt'
$ManagePy = Join-Path $ProjectDir 'manage.py'
$VenvDir = Join-Path $ProjectDir '.venv-cpu'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

function Invoke-Pip {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & $script:VenvPython -m pip @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed (exit code $LASTEXITCODE): $($Arguments -join ' ')"
    }
}

function Install-ProjectRequirements {
    param([string]$RequirementsFile)
    $filtered = @(
        Get-Content -LiteralPath $RequirementsFile | Where-Object {
            $_ -notmatch '^\s*(torch|torchaudio|torchvision|torchcodec)(\s*(===|==|~=|!=|<=|>=|<|>)|\s*$)'
        }
    )
    $temporaryRequirements = Join-Path $env:TEMP "voice-cloner-cpu-requirements-$PID.txt"
    try {
        $filtered | Set-Content -LiteralPath $temporaryRequirements -Encoding UTF8
        Invoke-Pip -Arguments @('install', '-r', $temporaryRequirements)
    }
    finally {
        Remove-Item -LiteralPath $temporaryRequirements -Force -ErrorAction SilentlyContinue
    }
}

Set-Location $ProjectDir
if (-not (Test-Path -LiteralPath $RequirementsPath)) { throw 'requirements.txt was not found beside this installer.' }
if (-not (Test-Path -LiteralPath $ManagePy)) { throw 'manage.py was not found. Put this installer in the Django project root.' }
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Python Launcher (py) was not found. Install 64-bit Python 3.11 first.' }

& py -3.11 -c "import platform, sys; print('Using Python:', sys.version); print('Architecture:', platform.machine()); assert platform.machine().lower() in ('amd64', 'x86_64'), '64-bit Python is required.'"
if ($LASTEXITCODE -ne 0) { throw '64-bit Python 3.11 was not found. Install it, then rerun this installer.' }

Write-Host 'Creating the Python 3.11 CPU environment...'
& py -3.11 -m venv $VenvDir
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) { throw 'Could not create the Python 3.11 virtual environment.' }

Write-Host 'Updating pip...'
Invoke-Pip -Arguments @('install', '--upgrade', 'pip', 'setuptools', 'wheel')

Write-Host 'Installing CPU-only PyTorch 2.8.0 and torchaudio 2.8.0...'
Invoke-Pip -Arguments @(
    'install',
    '--index-url', 'https://download.pytorch.org/whl/cpu',
    'torch==2.8.0',
    'torchaudio==2.8.0'
)

Write-Host 'Installing the remaining project requirements...'
Install-ProjectRequirements -RequirementsFile $RequirementsPath

Write-Host 'Verifying PyTorch, FFmpeg, and Coqui TTS...'
$verifyCode = @'
import shutil
import torch
import torchaudio
import static_ffmpeg
static_ffmpeg.add_paths()
from TTS.api import TTS
print("PyTorch:", torch.__version__)
print("torchaudio:", torchaudio.__version__)
print("GPU available:", torch.cuda.is_available())
ffmpeg_path = shutil.which("ffmpeg")
print("FFmpeg executable:", ffmpeg_path)
if not ffmpeg_path:
    raise SystemExit("static-ffmpeg did not add an FFmpeg executable to PATH.")
print("Coqui TTS import successful")
'@
$verifyFile = Join-Path $env:TEMP "voice-cloner-cpu-verify-$PID.py"
try {
    Set-Content -LiteralPath $verifyFile -Value $verifyCode -Encoding UTF8
    & $VenvPython $verifyFile
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch/FFmpeg/Coqui TTS verification failed.' }
}
finally {
    Remove-Item -LiteralPath $verifyFile -Force -ErrorAction SilentlyContinue
}

Write-Host 'Checking installed package compatibility...'
Invoke-Pip -Arguments @('check')

Write-Host 'Checking Django configuration and applying database migrations...'
& $VenvPython $ManagePy check
if ($LASTEXITCODE -ne 0) { throw 'Django system check failed.' }
& $VenvPython $ManagePy migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'Django database migrations failed.' }

Write-Host ''
Write-Host 'CPU installation completed. PyTorch, FFmpeg, Coqui, and Django checks passed.' -ForegroundColor Green
Write-Host "Environment: $VenvDir"
Write-Host 'To start Django:'
Write-Host '  .\.venv-cpu\Scripts\python.exe manage.py runserver'
Write-Host 'To activate this environment in the current PowerShell window:'
Write-Host '  . .\.venv-cpu\Scripts\Activate.ps1'
