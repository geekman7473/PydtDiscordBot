# setup-mappings.ps1
# Interactive script to generate Steam64 ID -> Discord ID mappings from a PYDT game

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$GameInput
)

# Extract game ID from URL or use as-is
if ($GameInput -match "playyourdamnturn\.com/game/([a-f0-9-]+)") {
    $GameId = $Matches[1]
} elseif ($GameInput -match "^[a-f0-9-]+$") {
    $GameId = $GameInput
} else {
    Write-Host "Invalid input. Please provide a PYDT game URL or game ID." -ForegroundColor Red
    exit 1
}

Write-Host "`nFetching game data for: $GameId" -ForegroundColor Cyan

# Fetch game data from PYDT API
try {
    $ApiUrl = "https://api.playyourdamnturn.com/game/$GameId"
    $GameData = Invoke-RestMethod -Uri $ApiUrl -ErrorAction Stop
} catch {
    Write-Host "Failed to fetch game data: $_" -ForegroundColor Red
    exit 1
}

Write-Host "Game: $($GameData.displayName)" -ForegroundColor Green
Write-Host "Players: $($GameData.humans)" -ForegroundColor Green
Write-Host ""

# We need to look up Steam usernames - fetch from Steam API or use steamId as fallback
# For now, we'll use the Steam Web API to get display names
function Get-SteamDisplayName {
    param([string]$SteamId)

    # Try to get display name from Steam - this requires no API key for public profiles
    try {
        $ProfileUrl = "https://steamcommunity.com/profiles/$SteamId/?xml=1"
        $Response = Invoke-WebRequest -Uri $ProfileUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        if ($Response.Content -match "<steamID><!\[CDATA\[(.+?)\]\]></steamID>") {
            return $Matches[1]
        }
    } catch {
        # Silently fail and return null
    }
    return $null
}

# Leader name mapping for display
$LeaderNames = @{
    "LEADER_BARBAROSSA" = "Frederick Barbarossa (Germany)"
    "LEADER_PETER_GREAT" = "Peter the Great (Russia)"
    "LEADER_SEONDEOK" = "Seondeok (Korea)"
    "LEADER_PHILIP_II" = "Philip II (Spain)"
    "LEADER_T_ROOSEVELT" = "Teddy Roosevelt (America)"
    "LEADER_HOJO" = "Hojo Tokimune (Japan)"
    "LEADER_GANDHI" = "Gandhi (India)"
    "LEADER_MONTEZUMA" = "Montezuma (Aztec)"
    "LEADER_CLEOPATRA" = "Cleopatra (Egypt)"
    "LEADER_VICTORIA" = "Victoria (England)"
    "LEADER_CATHERINE_DE_MEDICI" = "Catherine de Medici (France)"
    "LEADER_GORGO" = "Gorgo (Greece)"
    "LEADER_PERICLES" = "Pericles (Greece)"
    "LEADER_TRAJAN" = "Trajan (Rome)"
    "LEADER_TOMYRIS" = "Tomyris (Scythia)"
    "LEADER_HARDRADA" = "Harald Hardrada (Norway)"
    "LEADER_QIN" = "Qin Shi Huang (China)"
    "LEADER_SALADIN" = "Saladin (Arabia)"
    "LEADER_MVEMBA" = "Mvemba a Nzinga (Kongo)"
    "LEADER_GILGAMESH" = "Gilgamesh (Sumeria)"
    "LEADER_JADWIGA" = "Jadwiga (Poland)"
    "LEADER_JOHN_CURTIN" = "John Curtin (Australia)"
    "LEADER_ALEXANDER" = "Alexander (Macedon)"
    "LEADER_CYRUS" = "Cyrus (Persia)"
    "LEADER_AMANITORE" = "Amanitore (Nubia)"
    "LEADER_JAYAVARMAN" = "Jayavarman VII (Khmer)"
    "LEADER_GITARJA" = "Gitarja (Indonesia)"
    "LEADER_SHAKA" = "Shaka (Zulu)"
    "LEADER_ROBERT_THE_BRUCE" = "Robert the Bruce (Scotland)"
    "LEADER_TAMAR" = "Tamar (Georgia)"
    "LEADER_LAUTARO" = "Lautaro (Mapuche)"
    "LEADER_POUNDMAKER" = "Poundmaker (Cree)"
    "LEADER_CHANDRAGUPTA" = "Chandragupta (India)"
    "LEADER_WILHELMINA" = "Wilhelmina (Netherlands)"
    "LEADER_SULEIMAN" = "Suleiman (Ottoman)"
    "LEADER_GENGHIS_KHAN" = "Genghis Khan (Mongolia)"
    "LEADER_KRISTINA" = "Kristina (Sweden)"
    "LEADER_MANSA_MUSA" = "Mansa Musa (Mali)"
    "LEADER_MATTHIAS_CORVINUS" = "Matthias Corvinus (Hungary)"
    "LEADER_DIDO" = "Dido (Phoenicia)"
    "LEADER_PACHACUTI" = "Pachacuti (Inca)"
    "LEADER_ELEANOR_ENGLAND" = "Eleanor of Aquitaine (England)"
    "LEADER_ELEANOR_FRANCE" = "Eleanor of Aquitaine (France)"
    "LEADER_KUPE" = "Kupe (Maori)"
    "LEADER_WILFRID_LAURIER" = "Wilfrid Laurier (Canada)"
    "LEADER_MENELIK" = "Menelik II (Ethiopia)"
    "LEADER_SIMON_BOLIVAR" = "Simon Bolivar (Gran Colombia)"
    "LEADER_LADY_SIX_SKY" = "Lady Six Sky (Maya)"
    "LEADER_BA_TRIEU" = "Ba Trieu (Vietnam)"
    "LEADER_AMBIORIX" = "Ambiorix (Gaul)"
    "LEADER_BASIL" = "Basil II (Byzantium)"
    "LEADER_HAMMURABI" = "Hammurabi (Babylon)"
    "LEADER_JOAO_III" = "Joao III (Portugal)"
    "LEADER_KUBLAI_KHAN_CHINA" = "Kublai Khan (China)"
    "LEADER_KUBLAI_KHAN_MONGOLIA" = "Kublai Khan (Mongolia)"
}

function Get-LeaderDisplayName {
    param([string]$CivType)
    if ($LeaderNames.ContainsKey($CivType)) {
        return $LeaderNames[$CivType]
    }
    # Fallback: clean up the raw name
    return $CivType -replace "LEADER_", "" -replace "_", " "
}

# Collect mappings
$Mappings = @{}
$PlayerCount = $GameData.players.Count

Write-Host "=" * 60 -ForegroundColor DarkGray
Write-Host "Enter Discord IDs for each player." -ForegroundColor Yellow
Write-Host "Leave blank and press Enter to skip a player." -ForegroundColor Yellow
Write-Host "Discord IDs are 18-digit numbers (enable Developer Mode in Discord to copy them)." -ForegroundColor Yellow
Write-Host "=" * 60 -ForegroundColor DarkGray
Write-Host ""

$PlayerIndex = 0
foreach ($Player in $GameData.players) {
    $PlayerIndex++
    $SteamId = $Player.steamId
    $LeaderDisplay = Get-LeaderDisplayName -CivType $Player.civType

    # Try to get Steam display name
    Write-Host "Looking up Steam username..." -ForegroundColor DarkGray -NoNewline
    $SteamName = Get-SteamDisplayName -SteamId $SteamId
    Write-Host "`r                              `r" -NoNewline

    if ($SteamName) {
        Write-Host "[$PlayerIndex/$PlayerCount] " -ForegroundColor Cyan -NoNewline
        Write-Host "$SteamName" -ForegroundColor White -NoNewline
        Write-Host " playing as " -NoNewline
        Write-Host "$LeaderDisplay" -ForegroundColor Green
    } else {
        Write-Host "[$PlayerIndex/$PlayerCount] " -ForegroundColor Cyan -NoNewline
        Write-Host "Steam ID: $SteamId" -ForegroundColor White -NoNewline
        Write-Host " playing as " -NoNewline
        Write-Host "$LeaderDisplay" -ForegroundColor Green
    }

    Write-Host "  Steam64 ID: " -NoNewline -ForegroundColor DarkGray
    Write-Host $SteamId -ForegroundColor DarkYellow

    $DiscordId = Read-Host "  Discord ID"

    # Validate Discord ID format if provided
    if ($DiscordId -and $DiscordId -notmatch "^\d{17,20}$") {
        Write-Host "  Warning: '$DiscordId' doesn't look like a valid Discord ID (should be 17-20 digits)" -ForegroundColor Yellow
        $Confirm = Read-Host "  Use anyway? (y/N)"
        if ($Confirm -ne "y" -and $Confirm -ne "Y") {
            $DiscordId = ""
        }
    }

    # Always add to mapping (empty string if not provided)
    $Mappings[$SteamId] = $DiscordId

    if ($DiscordId) {
        Write-Host "  Mapped!" -ForegroundColor Green
    } else {
        Write-Host "  Skipped (will use PYDT username as fallback)" -ForegroundColor DarkGray
    }
    Write-Host ""
}

# Summary
Write-Host "=" * 60 -ForegroundColor DarkGray
Write-Host "SUMMARY" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor DarkGray

$MappedCount = ($Mappings.Values | Where-Object { $_ }).Count
$SkippedCount = $Mappings.Count - $MappedCount

Write-Host "Total players: $($Mappings.Count)"
Write-Host "Mapped to Discord: $MappedCount" -ForegroundColor Green
Write-Host "Using fallback: $SkippedCount" -ForegroundColor Yellow
Write-Host ""

# Convert to JSON
$JsonOutput = $Mappings | ConvertTo-Json -Compress

Write-Host "Generated mapping:" -ForegroundColor Cyan
Write-Host $JsonOutput
Write-Host ""

# Save to file
$OutputPath = Join-Path (Get-Location) "mappings.json"
$Mappings | ConvertTo-Json | Out-File -FilePath $OutputPath -Encoding UTF8
Write-Host "Saved to: $OutputPath" -ForegroundColor Green
Write-Host ""

# Offer to update GitHub secret
Write-Host "=" * 60 -ForegroundColor DarkGray
$UpdateSecret = Read-Host "Update USER_MAPPING_JSON secret in GitHub? (y/N)"

if ($UpdateSecret -eq "y" -or $UpdateSecret -eq "Y") {
    Write-Host "Updating GitHub secret..." -ForegroundColor Cyan

    try {
        # Check if gh is installed
        $null = Get-Command gh -ErrorAction Stop

        # Update the secret
        gh secret set USER_MAPPING_JSON --body $JsonOutput

        if ($LASTEXITCODE -eq 0) {
            Write-Host "GitHub secret updated successfully!" -ForegroundColor Green
            Write-Host ""
            Write-Host "To deploy the updated mapping, either:" -ForegroundColor Yellow
            Write-Host "  1. Push a commit to trigger the CI/CD pipeline" -ForegroundColor Yellow
            Write-Host "  2. Manually run: gh workflow run deploy.yml" -ForegroundColor Yellow
        } else {
            Write-Host "Failed to update GitHub secret. Make sure you're authenticated with 'gh auth login'" -ForegroundColor Red
        }
    } catch {
        Write-Host "GitHub CLI (gh) not found. Install it from https://cli.github.com/" -ForegroundColor Red
        Write-Host ""
        Write-Host "To manually set the secret, run:" -ForegroundColor Yellow
        Write-Host "  gh secret set USER_MAPPING_JSON --body '$JsonOutput'" -ForegroundColor White
    }
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
