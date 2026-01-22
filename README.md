# PYDT Discord Bot

A serverless Discord bot that notifies players when it's their turn in [Play Your Damn Turn](https://www.playyourdamnturn.com/) (PYDT) Civilization games.

When PYDT detects a new turn, it sends a webhook to this Azure Function, which posts a message to your Discord channel mentioning the correct player.

## Features

- Receives PYDT webhooks and posts to Discord
- Maps Steam64 IDs to Discord user IDs for @mentions
- Sends periodic reminders until the player takes their turn
- Runs on Azure Functions (essentially free for this use case)
- CI/CD via GitHub Actions

## Prerequisites

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) installed
- [GitHub CLI](https://cli.github.com/) installed (optional, for setting secrets via CLI)
- An Azure account (free tier works)
- A Discord server where you have permission to create webhooks
- A PYDT game where you can configure webhooks

## Setup Instructions

### 1. Fork this repo

Just use the Github UI

### 2. Create Azure Resources

Login to Azure and create the required resources:

```bash
# Login to Azure
az login

# Register required resource providers (first-time Azure setup)
az provider register --namespace Microsoft.Web
az provider register --namespace Microsoft.Storage

# Wait for registration to complete (check status)
az provider show --namespace Microsoft.Web --query "registrationState"
# Should show "Registered" before proceeding. This may take a long time.

# Set variables (customize these)
$LOCATION="westus"
$STORAGE_ACCOUNT="pydtbotstorage$(Get-Random)"  # Must be globally unique
$FUNCTION_APP="pydt-discord-bot-$(Get-Random)"   # Must be globally unique

# Create resource group
az group create --name pydt-bot-rg --location $LOCATION

# Create storage account (required for Azure Functions)
az storage account create --name $STORAGE_ACCOUNT --resource-group pydt-bot-rg --location $LOCATION --sku Standard_LRS --allow-blob-public-access false

# Create Function App (Flex Consumption plan). This also might take a long time.
az functionapp create --name $FUNCTION_APP --resource-group pydt-bot-rg --storage-account $STORAGE_ACCOUNT --flexconsumption-location $LOCATION --runtime python --runtime-version 3.11

# Get your subscription ID (for service principal)
$SUBSCRIPTION_ID = (az account show --query id -o tsv)

# Create a service principal with contributor access to your resource group
# Save the JSON output - you'll need it for the AZURE_CREDENTIALS GitHub secret
az ad sp create-for-rbac --name "github-deploy-pydt" --role contributor --scopes /subscriptions/$SUBSCRIPTION_ID/resourceGroups/pydt-bot-rg --json-auth

# Note your function app name - you'll need it later
echo "Your Function App name is: $FUNCTION_APP"
echo "Your webhook URL will be: https://$FUNCTION_APP.azurewebsites.net/api/pydt-webhook"
```

**Important outputs to save:**
- The **JSON output** from `az ad sp create-for-rbac` (for `AZURE_CREDENTIALS` secret)
- Your **Function App name**

### 3. Create Discord Webhook

1. Open Discord and go to your server
2. Right-click the channel where you want notifications → **Edit Channel**
3. Go to **Integrations** → **Webhooks**
4. Click **New Webhook**
5. Name it something like "PYDT Turn Bot"
6. Click **Copy Webhook URL** and save it for later

### 4. Generate Player Mappings

Use the included setup script to automatically fetch players from your PYDT game and create the Steam64 ID → Discord ID mappings.

**Prerequisites:**
- Enable **Developer Mode** in Discord: User Settings → Advanced → Developer Mode
- This lets you right-click users to copy their Discord ID

**Run the setup script:**

```powershell
# Using the game URL
.\setup-mappings.ps1 "https://www.playyourdamnturn.com/game/YOUR-GAME-ID"

# Or just the game ID
.\setup-mappings.ps1 "YOUR-GAME-ID"
```

The script will:
1. Fetch all players from your PYDT game
2. Look up each player's Steam username
3. Prompt you to enter each player's Discord ID
4. Save the mapping to `mappings.json`
5. Optionally update the GitHub secret automatically

> **Note:** If a player's Discord ID is left empty, the bot will fall back to using their PYDT username instead of an @mention, with a warning that the mapping is incomplete.

### 5. Configure GitHub Secrets

You need to add four secrets to your GitHub repository. If you used the setup script and chose to update the GitHub secret, `USER_MAPPING_JSON` is already configured.

#### Option A: Using GitHub CLI

```bash
# Set the function app name
gh secret set AZURE_FUNCTIONAPP_NAME --body "pydt-discord-bot-1234567890"

# Set Discord webhook URL
gh secret set DISCORD_WEBHOOK_URL --body "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"

# Set user mapping (if not already set by setup-mappings.ps1)
gh secret set USER_MAPPING_JSON --body '{"76561198012345678": "123456789012345678", "76561198023456789": "234567890123456789"}'

# Set Azure credentials (paste the JSON from step 2 when prompted, then Ctrl+D)
gh secret set AZURE_CREDENTIALS
```

#### Option B: Using GitHub Web UI

1. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** for each:

| Secret Name | Value |
|-------------|-------|
| `AZURE_FUNCTIONAPP_NAME` | Your function app name from step 2 |
| `DISCORD_WEBHOOK_URL` | Your Discord webhook URL from step 3 |
| `USER_MAPPING_JSON` | Contents of `mappings.json` from step 4 |
| `AZURE_CREDENTIALS` | The entire JSON output from step 2 |

### 6. Deploy

Push to main to trigger the GitHub Actions deployment:

```bash
git add .
git commit -m "Configure function app name"
git push
```

Monitor the deployment in your repo's **Actions** tab.

### 7. Configure PYDT

1. Go to [playyourdamnturn.com](https://www.playyourdamnturn.com/)
2. Open your game → **Edit Game** (or game settings)
3. Find the **Webhook URL** field
4. Enter your function URL:
   ```
   https://YOUR_FUNCTION_APP.azurewebsites.net/api/pydt-webhook
   ```
5. Save the settings

### 8. Test It

Take a turn in your Civ game and upload it to PYDT. The next player should receive a Discord notification!

You can also test manually:

```bash
curl -X POST "https://$FUNCTION_APP.azurewebsites.net/api/pydt-webhook" \
  -H "Content-Type: application/json" \
  -d '{"gameName": "Test Game", "userName": "SteamPlayer1", "steamId": "76561198012345678", "round": "42", "civName": "America", "leaderName": "Teddy Roosevelt"}'
```

To check active games being tracked:

```bash
curl "https://$FUNCTION_APP.azurewebsites.net/api/active-games"
```


### Blackout Period

Reminders are **not sent during configured quiet hours** to avoid waking people up at night. By default, no reminders are sent between **midnight and 7am Eastern time (GMT-5)**.

You can customize this in `config.json`:

```json
{
  "blackout": {
    "enabled": true,
    "startHour": 0,
    "endHour": 7,
    "gmtOffset": -5
  },
  "reminderThresholdHours": 2
}
```

| Setting | Description |
|---------|-------------|
| `enabled` | Set to `false` to disable blackout (reminders 24/7) |
| `startHour` | Hour when blackout starts (0-23, in local timezone) |
| `endHour` | Hour when blackout ends (0-23, in local timezone) |
| `gmtOffset` | Timezone offset from GMT (e.g., -5 for Eastern, -8 for Pacific) |
| `reminderThresholdHours` | How long a turn must be pending before reminders start |

> **Note:** Daylight saving time is not handled automatically. Adjust `gmtOffset` manually if needed (e.g., -4 for EDT, -5 for EST).

## Updating User Mappings

When players join or leave, re-run the setup script:

```powershell
.\setup-mappings.ps1 "YOUR-GAME-ID"
```

The script will prompt you for Discord IDs and offer to update the GitHub secret automatically.

Alternatively, manually update the `USER_MAPPING_JSON` secret in GitHub and trigger a deployment.

## Troubleshooting

### Forgot your Function App name?

```bash
az functionapp list --resource-group pydt-bot-rg --query "[].name" -o tsv
```

### Webhook not working

1. Check the function is deployed:
   ```bash
   az functionapp function list --name $FUNCTION_APP --resource-group pydt-bot-rg
   ```

2. Check the logs in the Azure Portal:
   - Go to Azure Portal → Function App → **Functions** → **pydt_webhook** → **Monitor**
   - Or: Function App → **Log stream** (may need to enable Application Insights first)

3. Verify app settings are configured:
   ```bash
   az functionapp config appsettings list --name $FUNCTION_APP --resource-group pydt-bot-rg
   ```

### Discord mentions not working

- Verify the Discord user ID is correct (18-digit number)
- Make sure the Steam64 ID in the mapping is correct (17-digit number like `76561198012345678`)
- Check the function logs for "No Discord ID configured" warnings

### GitHub Actions failing

- Verify the publish profile secret is the complete XML
- Check that the function app name in `deploy.yml` matches your Azure resource

## Cost

- **Azure Functions Flex Consumption Plan:** First 250k executions/month free

## License

MIT
