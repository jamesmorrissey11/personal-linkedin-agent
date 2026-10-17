# azd runs this from deploy/azure; the app reads .env from the repo root.
$envFile = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "../../..")) ".env"

# Clear the contents of the .env file
Set-Content -Path $envFile -Value ""

# Append new values to the .env file
$azureTenantId = azd env get-value AZURE_TENANT_ID
$azureOpenAiService = azd env get-value AZURE_OPENAI_SERVICE
$azureOpenAiEndpoint = azd env get-value AZURE_OPENAI_ENDPOINT
$azureOpenAiChatDeployment = azd env get-value AZURE_OPENAI_CHAT_DEPLOYMENT
$azureOpenAiChatModel = azd env get-value AZURE_OPENAI_CHAT_MODEL

Add-Content -Path $envFile -Value "AZURE_TENANT_ID=$azureTenantId"
Add-Content -Path $envFile -Value "AZURE_OPENAI_SERVICE=$azureOpenAiService"
Add-Content -Path $envFile -Value "AZURE_OPENAI_ENDPOINT=$azureOpenAiEndpoint"
Add-Content -Path $envFile -Value "AZURE_OPENAI_CHAT_DEPLOYMENT=$azureOpenAiChatDeployment"
Add-Content -Path $envFile -Value "AZURE_OPENAI_CHAT_MODEL=$azureOpenAiChatModel"
