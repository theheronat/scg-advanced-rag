#!/bin/bash
# Universal Settings Deployment Script for Azure Functions
# Supports multiple tenants and subscriptions
# Usage: ./deploy-settings-universal.sh [environment] [settings-file]
#
# Examples:
#   ./deploy-settings-universal.sh dev
#   ./deploy-settings-universal.sh prod settings-prod.json
#   ./deploy-settings-universal.sh staging settings-staging.json

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ENVIRONMENT="${1:-dev}"
SETTINGS_FILE="${2:-settings-${ENVIRONMENT}.json}"

echo -e "${BLUE}⚙️  Universal Settings Deployment${NC}"
echo -e "${BLUE}===================================${NC}"
echo ""
echo -e "${YELLOW}Environment: ${ENVIRONMENT}${NC}"
echo -e "${YELLOW}Settings File: ${SETTINGS_FILE}${NC}"
echo ""

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo -e "${RED}❌ jq is required but not installed.${NC}"
    echo -e "${YELLOW}Install with: brew install jq${NC}"
    exit 1
fi

# Load deployment configuration
CONFIG_FILE="deploy-config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}❌ Configuration file not found: $CONFIG_FILE${NC}"
    exit 1
fi

# Check if settings file exists
if [ ! -f "$SETTINGS_FILE" ]; then
    echo -e "${YELLOW}⚠️  Settings file not found: $SETTINGS_FILE${NC}"
    echo -e "${YELLOW}Creating template from local.settings.json...${NC}"

    if [ ! -f "local.settings.json" ]; then
        echo -e "${RED}❌ local.settings.json not found${NC}"
        exit 1
    fi

    # Extract Values section from local.settings.json (excluding AzureWebJobsStorage and FUNCTIONS_WORKER_RUNTIME)
    jq '.Values | to_entries | map(select(.key != "AzureWebJobsStorage" and .key != "FUNCTIONS_WORKER_RUNTIME")) | from_entries' local.settings.json > "$SETTINGS_FILE"

    echo -e "${GREEN}✓ Template settings file created: $SETTINGS_FILE${NC}"
    echo -e "${YELLOW}Please review and update the settings before deploying.${NC}"
    exit 0
fi

echo -e "${GREEN}📋 Loading configuration...${NC}"

# Parse deployment configuration
TENANT_ID=$(jq -r ".environments.${ENVIRONMENT}.tenant_id" "$CONFIG_FILE")
SUBSCRIPTION_ID=$(jq -r ".environments.${ENVIRONMENT}.subscription_id" "$CONFIG_FILE")
SUBSCRIPTION_NAME=$(jq -r ".environments.${ENVIRONMENT}.subscription_name" "$CONFIG_FILE")
RESOURCE_GROUP=$(jq -r ".environments.${ENVIRONMENT}.resource_group" "$CONFIG_FILE")
FUNCTION_APP_NAME=$(jq -r ".environments.${ENVIRONMENT}.function_app_name" "$CONFIG_FILE")

# Validate configuration
if [ "$SUBSCRIPTION_ID" = "null" ] || [ -z "$SUBSCRIPTION_ID" ]; then
    echo -e "${RED}❌ Invalid configuration for environment: ${ENVIRONMENT}${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Configuration loaded${NC}"
echo -e "  Subscription: ${SUBSCRIPTION_NAME}"
echo -e "  Resource Group: ${RESOURCE_GROUP}"
echo -e "  Function App: ${FUNCTION_APP_NAME}"
echo ""

# Check Azure CLI login
echo -e "${GREEN}🔐 Checking Azure CLI authentication...${NC}"
if ! az account show &> /dev/null; then
    echo -e "${YELLOW}⚠️  Not logged in to Azure${NC}"

    if [ -n "$TENANT_ID" ] && [ "$TENANT_ID" != "null" ]; then
        echo -e "${BLUE}Logging in with tenant: ${TENANT_ID}${NC}"
        az login --tenant "$TENANT_ID"
    else
        echo -e "${BLUE}Logging in...${NC}"
        az login
    fi
fi

# Switch subscription if needed
CURRENT_SUBSCRIPTION=$(az account show --query id -o tsv)
if [ "$CURRENT_SUBSCRIPTION" != "$SUBSCRIPTION_ID" ]; then
    echo -e "${YELLOW}🔄 Switching to subscription: ${SUBSCRIPTION_ID}${NC}"
    az account set --subscription "$SUBSCRIPTION_ID"
    echo -e "${GREEN}✓ Subscription switched${NC}"
    echo ""
fi

# Parse settings from JSON file and build az command
echo -e "${GREEN}🔧 Deploying application settings...${NC}"

# Convert JSON to space-separated key=value pairs
SETTINGS_ARRAY=$(jq -r 'to_entries | map("\(.key)=\(.value)") | .[]' "$SETTINGS_FILE")

# Build the az command
CMD="az functionapp config appsettings set --name \"$FUNCTION_APP_NAME\" --resource-group \"$RESOURCE_GROUP\" --settings"

while IFS= read -r setting; do
    CMD="$CMD \"$setting\""
done <<< "$SETTINGS_ARRAY"

# Execute the command
eval $CMD > /dev/null 2>&1

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to deploy settings${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Application settings deployed successfully${NC}"
echo ""

# Restart Function App to apply new settings
echo -e "${GREEN}🔄 Restarting Function App to apply settings...${NC}"
az functionapp restart \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$RESOURCE_GROUP"

echo ""
echo -e "${GREEN}✅ Settings deployment completed!${NC}"
echo ""
echo -e "${BLUE}🔍 To verify settings:${NC}"
echo -e "  az functionapp config appsettings list --name ${FUNCTION_APP_NAME} --resource-group ${RESOURCE_GROUP}"
echo ""
