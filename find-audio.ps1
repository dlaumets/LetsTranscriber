param(
    [string]$Path
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$transcribe = Join-Path $root "transcribe.cmd"

$extensions = @(".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".webm", ".aac")

function Resolve-AudioPath {
    param([string]$Candidate)

    if (-not $Candidate) { return $null }

    $resolved = Resolve-Path -LiteralPath $Candidate -ErrorAction SilentlyContinue
    if ($resolved) { return $resolved.Path }

    return $null
}

$audioPath = Resolve-AudioPath -Candidate $Path

if (-not $audioPath) {
    $downloads = Join-Path $env:USERPROFILE "Downloads"
    $files = Get-ChildItem -Path $downloads -File -ErrorAction SilentlyContinue |
        Where-Object { $extensions -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object LastWriteTime -Descending

    if ($files.Count -eq 0) {
        Write-Error "No audio files found in Downloads. Attach a voice message or pass a path."
        exit 1
    }

    $audioPath = $files[0].FullName
    Write-Host "Using latest audio: $audioPath"
}

& $transcribe $audioPath
exit $LASTEXITCODE
