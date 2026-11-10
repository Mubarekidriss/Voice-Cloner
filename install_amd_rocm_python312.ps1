# Voice Cloner - AMD Radeon GPU installer (Windows 11, Python 3.12)
# Run from the project root:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install_amd_rocm_python312.ps1

$ErrorActionPreference = 'Stop'
$ProjectDir = $PSScriptRoot
$Requirements = Join-Path $ProjectDir 'requirements.txt'
$ManagePy = Join-Path $ProjectDir 'manage.py'
$Venv = Join-Path $ProjectDir '.venv-amd'
$Python = Join-Path $Venv 'Scripts\python.exe'
$Site = Join-Path $Venv 'Lib\site-packages'
$Rocm = 'https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1'

# Avoid large numerical-library thread pools during installation.
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'

# Persist MIOpen performance settings for this Windows user and apply them
# immediately to this installer process. Future terminals/VS Code sessions
# inherit these values, so users do not need to configure them manually.
if (-not $env:LOCALAPPDATA) {
    throw 'LOCALAPPDATA is not available; cannot configure the MIOpen cache.'
}
$MIOpenRoot = Join-Path $env:LOCALAPPDATA 'VoiceCloner\miopen'
$MIOpenDbPath = Join-Path $MIOpenRoot 'db'
$MIOpenCachePath = Join-Path $MIOpenRoot 'cache'
New-Item -ItemType Directory -Force -Path $MIOpenDbPath, $MIOpenCachePath | Out-Null

$MIOpenSettings = [ordered]@{
    MIOPEN_FIND_MODE = 'FAST'
    MIOPEN_USER_DB_PATH = $MIOpenDbPath
    MIOPEN_CUSTOM_CACHE_DIR = $MIOpenCachePath
}
foreach ($setting in $MIOpenSettings.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable(
        $setting.Key,
        $setting.Value,
        [EnvironmentVariableTarget]::User
    )
    Set-Item -Path ("Env:{0}" -f $setting.Key) -Value $setting.Value
}
Write-Host 'MIOpen FAST mode and persistent user cache configured.' -ForegroundColor Green

function Invoke-Pip([string[]]$PipArgs) {
    & $script:Python -m pip @PipArgs
    if ($LASTEXITCODE -ne 0) { throw "pip failed: $($PipArgs -join ' ')" }
}

Set-Location $ProjectDir
if (!(Test-Path $Requirements) -or !(Test-Path $ManagePy)) {
    throw 'Place this installer beside requirements.txt and manage.py.'
}
if (!(Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python Launcher (py) not found. Install 64-bit Python 3.12 from python.org.'
}

# Remove the previous startup hooks BEFORE invoking this environment's Python.
foreach ($file in @(
    'voice_cloner_torchaudio_compat.pth', 'voice_cloner_torchaudio_compat.py',
    'voice_cloner_ffmpeg_bootstrap.pth', 'voice_cloner_ffmpeg_bootstrap.py'
)) {
    Remove-Item (Join-Path $Site $file) -Force -ErrorAction SilentlyContinue
}

& py -3.12 -c "import platform,sys; print(sys.version); assert platform.machine().lower() in ('amd64','x86_64'), '64-bit Python required'"
if ($LASTEXITCODE -ne 0) { throw '64-bit Python 3.12 is required.' }

Write-Host 'Creating/updating the AMD Python environment...'
& py -3.12 -m venv $Venv
if ($LASTEXITCODE -ne 0 -or !(Test-Path $Python)) { throw 'Could not create .venv-amd.' }

Invoke-Pip @('install', '--upgrade', 'pip', 'setuptools', 'wheel')

Write-Host 'Installing ROCm 7.2.1 runtime...'
Invoke-Pip @(
    'install', '--no-cache-dir',
    "$Rocm/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl",
    "$Rocm/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl",
    "$Rocm/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl",
    "$Rocm/rocm-7.2.1.tar.gz"
)

Write-Host 'Installing AMD PyTorch 2.9.1 + ROCm 7.2.1...'
Invoke-Pip @(
    'install', '--no-cache-dir',
    "$Rocm/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
    "$Rocm/torchaudio-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
    "$Rocm/torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl"
)

# requirements.txt may contain CPU PyTorch pins; this installer supplies the AMD builds.
$FilteredRequirements = Join-Path $env:TEMP "voice-cloner-req-$PID.txt"
try {
    Get-Content $Requirements | Where-Object {
        $_ -notmatch '^\s*(torch|torchaudio|torchvision|torchcodec)(\s*(===|==|~=|!=|<=|>=|<|>)|\s*$)'
    } | Set-Content $FilteredRequirements -Encoding UTF8
    Invoke-Pip @('install', '-r', $FilteredRequirements)
}
finally {
    Remove-Item $FilteredRequirements -Force -ErrorAction SilentlyContinue
}

Write-Host 'Removing incompatible TorchCodec and ensuring SoundFile is installed...'
& $Python -m pip uninstall --yes torchcodec
if ($LASTEXITCODE -ne 0) { throw 'Could not uninstall TorchCodec.' }
Invoke-Pip @('install', '--no-cache-dir', 'soundfile>=0.12.1,<1')

Write-Host 'Patching TorchAudio audio I/O and Coqui preflight check...'
$TorchaudioInit = Join-Path $Site 'torchaudio\__init__.py'
$CoquiInit = Join-Path $Site 'TTS\__init__.py'
if (!(Test-Path $TorchaudioInit) -or !(Test-Path $CoquiInit)) {
    throw 'TorchAudio or Coqui files were not found after installation.'
}

$AudioText = [IO.File]::ReadAllText($TorchaudioInit)
if (!$AudioText.Contains('VOICE_CLONER_SOUNDFILE_COMPAT')) {
    $AudioPatch = @'

# VOICE_CLONER_SOUNDFILE_COMPAT
# XTTS uses WAV files; route torchaudio.load/save through SoundFile.
import numpy as _vc_np
import soundfile as _vc_sf
import torch as _vc_torch

def _vc_load(uri, frame_offset=0, num_frames=-1, normalize=True,
             channels_first=True, format=None, buffer_size=4096, backend=None):
    if frame_offset < 0 or (num_frames is not None and num_frames < -1):
        raise ValueError("Invalid frame_offset or num_frames")
    frames = -1 if num_frames is None or num_frames == -1 else num_frames
    audio, rate = _vc_sf.read(uri, start=frame_offset, frames=frames,
                              dtype="float32", always_2d=True)
    if channels_first:
        audio = audio.T
    return _vc_torch.from_numpy(_vc_np.ascontiguousarray(audio)), int(rate)

def _vc_save(uri, src, sample_rate, channels_first=True, format=None,
             encoding=None, bits_per_sample=None, buffer_size=4096,
             backend=None, compression=None):
    audio = src.detach().cpu().numpy() if isinstance(src, _vc_torch.Tensor) else _vc_np.asarray(src)
    if audio.ndim == 2 and channels_first:
        audio = audio.T
    elif audio.ndim not in (1, 2):
        raise ValueError("Audio must be a 1D or 2D tensor/array")
    subtype = {8: "PCM_U8", 16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}.get(bits_per_sample)
    if encoding and str(encoding).upper() in ("PCM_F", "FLOAT"):
        subtype = "FLOAT"
    _vc_sf.write(uri, audio, int(sample_rate), format=format, subtype=subtype)

_vc_load._voice_cloner_soundfile_compat = True
_vc_save._voice_cloner_soundfile_compat = True
load = load_with_torchcodec = _vc_load
save = save_with_torchcodec = _vc_save
'@
    [IO.File]::AppendAllText($TorchaudioInit, $AudioPatch, [Text.UTF8Encoding]::new($false))
}

$CoquiText = [IO.File]::ReadAllText($CoquiInit)
if (!$CoquiText.Contains('VOICE_CLONER_TORCHCODEC_PREFLIGHT_BYPASSED')) {
    $Guard = '(?m)^if is_torch_greater_or_equal\("2\.9"\):\r?\n    if not is_torchcodec_available\(\):\r?\n        raise ImportError\(TORCHCODEC_IMPORT_ERROR\)\r?\n?'
    $CoquiPatched = ([regex]::new($Guard)).Replace(
        $CoquiText,
        '# VOICE_CLONER_TORCHCODEC_PREFLIGHT_BYPASSED: SoundFile supplies torchaudio.load/save.' + [Environment]::NewLine,
        1
    )
    if ($CoquiPatched -eq $CoquiText) {
        throw 'Coqui 0.27.5 TorchCodec check was not found; no unsupported source change was made.'
    }
    [IO.File]::WriteAllText($CoquiInit, $CoquiPatched, [Text.UTF8Encoding]::new($false))
}

# No .pth startup hook remains; ordinary Python commands do not load PyTorch automatically.
& $Python -c "import sys; assert 'torch' not in sys.modules; print('Python startup OK (PyTorch not preloaded).')"
if ($LASTEXITCODE -ne 0) { throw 'Unexpected PyTorch startup import.' }

Write-Host 'Verifying AMD GPU, Coqui, SoundFile, and FFmpeg...'
$Verify = @'
import shutil, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf
import torch, torchaudio, static_ffmpeg
from TTS.api import TTS

static_ffmpeg.add_paths()
print("PyTorch:", torch.__version__, "HIP:", torch.version.hip)
if not torch.cuda.is_available():
    raise SystemExit("AMD GPU is not available to PyTorch.")
print("GPU:", torch.cuda.get_device_name(0))
print("GPU tensor test:", (torch.tensor([1.0], device="cuda") * 2).item())
if not getattr(torchaudio.load, "_voice_cloner_soundfile_compat", False):
    raise SystemExit("SoundFile load patch was not applied.")
if not getattr(torchaudio.save, "_voice_cloner_soundfile_compat", False):
    raise SystemExit("SoundFile save patch was not applied.")
with tempfile.TemporaryDirectory() as folder:
    wav = Path(folder) / "test.wav"
    out = Path(folder) / "out.wav"
    sf.write(wav, np.zeros(1600, dtype=np.float32), 16000)
    samples, rate = torchaudio.load(str(wav))
    if samples.shape != (1, 1600) or rate != 16000:
        raise SystemExit("SoundFile audio-load test failed.")
    torchaudio.save(str(out), samples, rate)
    if not out.exists():
        raise SystemExit("SoundFile audio-save test failed.")
ffmpeg = shutil.which("ffmpeg")
print("FFmpeg:", ffmpeg)
if not ffmpeg:
    raise SystemExit("static-ffmpeg is not available on PATH.")
print("Coqui TTS import and audio I/O checks passed.")
'@
$VerifyFile = Join-Path $env:TEMP "voice-cloner-verify-$PID.py"
try {
    Set-Content $VerifyFile $Verify -Encoding UTF8
    & $Python $VerifyFile
    if ($LASTEXITCODE -ne 0) { throw 'AMD/Coqui/audio verification failed.' }
}
finally {
    Remove-Item $VerifyFile -Force -ErrorAction SilentlyContinue
}

Invoke-Pip @('check')
& $Python $ManagePy check
if ($LASTEXITCODE -ne 0) { throw 'Django check failed.' }
& $Python $ManagePy migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'Django migrations failed.' }

Write-Host 'Installation checks passed.' -ForegroundColor Green
Write-Host 'Persistent MIOpen settings:'
Write-Host '  MIOPEN_FIND_MODE=FAST'
Write-Host ("  MIOPEN_USER_DB_PATH={0}" -f $MIOpenDbPath)
Write-Host ("  MIOPEN_CUSTOM_CACHE_DIR={0}" -f $MIOpenCachePath)
Write-Host 'Run the application with:'
Write-Host '  .\.venv-amd\Scripts\python.exe manage.py runserver'
Write-Host 'Restart VS Code once so it inherits the newly saved user environment variables.' -ForegroundColor Yellow
