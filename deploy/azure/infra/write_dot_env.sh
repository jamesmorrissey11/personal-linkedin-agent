#!/bin/bash

# azd runs this from deploy/azure; the app reads .env from the repo root.
ENV_FILE="$(cd "$(dirname "$0")/../../.." && pwd)/.env"

# Clear the contents of the .env file
: > "$ENV_FILE"

# Append new values to the .env file
echo "AZURE_TENANT_ID=$(azd env get-value AZURE_TENANT_ID)" >> "$ENV_FILE"
echo "AZURE_OPENAI_SERVICE=$(azd env get-value AZURE_OPENAI_SERVICE)" >> "$ENV_FILE"
echo "AZURE_OPENAI_ENDPOINT=$(azd env get-value AZURE_OPENAI_ENDPOINT)" >> "$ENV_FILE"
echo "AZURE_OPENAI_CHAT_DEPLOYMENT=$(azd env get-value AZURE_OPENAI_CHAT_DEPLOYMENT)" >> "$ENV_FILE"
echo "AZURE_OPENAI_CHAT_MODEL=$(azd env get-value AZURE_OPENAI_CHAT_MODEL)" >> "$ENV_FILE"
