param(
    [Parameter(Mandatory = $true)]
    [string]$Token
)

$Owner = "jestkent"
$Repo = "LyreAura"
$Tag = "v1.0.0"
$ExePath = "d:\Desktop\LyreAura\LyreAura.exe"

$headers = @{
    Authorization          = "Bearer $Token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

# Step 1: Create the release
Write-Host "Creating release $Tag ..." -ForegroundColor Cyan

$releaseBody = "## LyreAura v1.0.0`n`nA lightweight Pomodoro productivity timer + YouTube Music player for Windows.`nNo Python installation required -- just download and run!`n`n### Features`n- Pomodoro Timer with circular countdown and stand-up reminders`n- YouTube Music search and streaming (requires free YouTube Data API v3 key)`n- Queue system with reordering and auto-advance`n- Playlist manager -- create, save, load, delete`n- Session restore -- your queue and songs survive restarts`n- Volume control with mute/unmute`n- System tray support`n- Resizable and scrollable UI`n`n### Quick Start`n1. Download LyreAura.exe below`n2. Place it in its own folder (e.g. D:\LyreAura\)`n3. In the same folder, create a file called .env containing:`n   YOUTUBE_API_KEY=your_key_here`n   (Or just launch the app -- it will prompt you for the key on first run)`n4. Double-click LyreAura.exe`n`nGet a free YouTube Data API v3 key at https://console.cloud.google.com"

$bodyObj = [PSCustomObject]@{
    tag_name         = $Tag
    target_commitish = "main"
    name             = "LyreAura v1.0.0 - Pomodoro + YouTube Music Player"
    body             = $releaseBody
    draft            = $false
    prerelease       = $false
}

$bodyJson = $bodyObj | ConvertTo-Json -Depth 5

try {
    $release = Invoke-RestMethod `
        -Uri         "https://api.github.com/repos/$Owner/$Repo/releases" `
        -Method      POST `
        -Headers     $headers `
        -Body        $bodyJson `
        -ContentType "application/json"

    Write-Host "Release created! ID: $($release.id)" -ForegroundColor Green
    Write-Host "Release URL: $($release.html_url)" -ForegroundColor Green
}
catch {
    Write-Host "ERROR creating release: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Step 2: Upload LyreAura.exe
Write-Host "`nUploading LyreAura.exe ..." -ForegroundColor Cyan

$uploadBase = $release.upload_url -replace '\{\?name,label\}', ''
$fileBytes = [System.IO.File]::ReadAllBytes($ExePath)
$uploadHdrs = @{
    Authorization          = "Bearer $Token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "Content-Type"         = "application/octet-stream"
}

try {
    $asset = Invoke-RestMethod `
        -Uri     "$($uploadBase)?name=LyreAura.exe" `
        -Method  POST `
        -Headers $uploadHdrs `
        -Body    $fileBytes

    Write-Host "Upload complete!" -ForegroundColor Green
    Write-Host "Download URL: $($asset.browser_download_url)" -ForegroundColor Green
}
catch {
    Write-Host "ERROR uploading exe: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Release was created -- upload the exe manually at: $($release.html_url)/edit"
    exit 1
}

Write-Host "`nDone! Release is live at:" -ForegroundColor Green
Write-Host "  $($release.html_url)" -ForegroundColor Yellow
