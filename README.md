# PYDT Discord Bot

A serverless Discord bot that notifies players when it's their turn in [Play Your Damn Turn](https://www.playyourdamnturn.com/) (PYDT) Civilization games.

When PYDT detects a new turn, it sends a webhook to this Azure Function, which posts a message to your Discord channel mentioning the correct player.

## Features

- Receives PYDT webhooks and posts to Discord
- Maps Steam usernames to Discord user IDs for @mentions
- Falls back to displaying Steam username if no mapping exists
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

### 4. Get Discord User IDs

You need each player's Discord user ID to enable @mentions.

1. In Discord, go to **User Settings** → **Advanced** → Enable **Developer Mode**
2. Right-click each player's name → **Copy User ID**
3. Create a JSON mapping of Steam usernames to Discord IDs:

```json
{
  "SteamPlayer1": "123456789012345678",
  "SteamPlayer2": "234567890123456789",
  "AnotherPlayer": "345678901234567890"
}
```

> **Tip:** Steam usernames are what PYDT shows for each player. Check your PYDT game page to see the exact usernames.

### 5. Configure GitHub Secrets

You need to add four secrets to your GitHub repository.

#### Option A: Using GitHub CLI

```bash
# Set the function app name
gh secret set AZURE_FUNCTIONAPP_NAME --body "pydt-discord-bot-1234567890"

# Set Discord webhook URL
gh secret set DISCORD_WEBHOOK_URL --body "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"

# Set user mapping (use single quotes to preserve JSON)
gh secret set USER_MAPPING_JSON --body '{"SteamPlayer1": "123456789012345678", "SteamPlayer2": "234567890123456789"}'

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
| `USER_MAPPING_JSON` | Your JSON mapping from step 4 |
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
  -d '{"gameName": "Test Game", "userName": "SteamPlayer1", "round": "42", "civName": "America", "leaderName": "Teddy Roosevelt"}'
```

## Updating User Mappings

When players join or leave:

1. Update the `USER_MAPPING_JSON` secret in GitHub (Settings → Secrets → Actions)
2. Go to Actions → "Deploy to Azure Functions" → Run workflow → Run workflow

The workflow will push the updated mapping to Azure.

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
- Make sure the Steam username in the mapping matches exactly what PYDT sends
- Check the function logs for "No Discord mapping found" warnings

### GitHub Actions failing

- Verify the publish profile secret is the complete XML
- Check that the function app name in `deploy.yml` matches your Azure resource

## Cost

- **Azure Functions Consumption Plan:** First 1 million executions/month free
- **Storage Account:** ~$0.01-0.05/month
- **Total:** Essentially free for typical Civ game usage

## License

MIT
