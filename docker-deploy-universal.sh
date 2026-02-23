#!/bin/bash
# Universal Docker Deployment Script for Azure Functions
# Supports multiple tenants and subscriptions
# Usage: ./docker-deploy-universal.sh [environment] [options]
#
# Examples:
#   ./docker-deploy-universal.sh dev
#   ./docker-deploy-universal.sh prod --build-only
#   ./docker-deploy-universal.sh staging --no-cache

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
ENVIRONMENT="${1:-dev}"
BUILD_ONLY=false
NO_CACHE=false
SKIP_TESTS=false
IMAGE_TAG="latest"

# Parse arguments
shift || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}🐳 Universal Docker Deployment to Azure Function${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${YELLOW}Environment: ${ENVIRONMENT}${NC}"
echo -e "${YELLOW}Image Tag: ${IMAGE_TAG}${NC}"
echo ""

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo -e "${RED}❌ jq is required but not installed.${NC}"
    echo -e "${YELLOW}Install with: brew install jq${NC}"
    exit 1
fi

# Load configuration from JSON
CONFIG_FILE="deploy-config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}❌ Configuration file not found: $CONFIG_FILE${NC}"
    exit 1
fi

echo -e "${GREEN}📋 Loading configuration...${NC}"

# Parse configuration
TENANT_ID=$(jq -r ".environments.${ENVIRONMENT}.tenant_id" "$CONFIG_FILE")
SUBSCRIPTION_ID=$(jq -r ".environments.${ENVIRONMENT}.subscription_id" "$CONFIG_FILE")
SUBSCRIPTION_NAME=$(jq -r ".environments.${ENVIRONMENT}.subscription_name" "$CONFIG_FILE")
RESOURCE_GROUP=$(jq -r ".environments.${ENVIRONMENT}.resource_group" "$CONFIG_FILE")
FUNCTION_APP_NAME=$(jq -r ".environments.${ENVIRONMENT}.function_app_name" "$CONFIG_FILE")
ACR_NAME=$(jq -r ".environments.${ENVIRONMENT}.acr_name" "$CONFIG_FILE")
ACR_LOGIN_SERVER=$(jq -r ".environments.${ENVIRONMENT}.acr_login_server" "$CONFIG_FILE")
LOCATION=$(jq -r ".environments.${ENVIRONMENT}.location" "$CONFIG_FILE")

# Validate configuration
if [ "$SUBSCRIPTION_ID" = "null" ] || [ -z "$SUBSCRIPTION_ID" ]; then
    echo -e "${RED}❌ Invalid configuration for environment: ${ENVIRONMENT}${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Configuration loaded${NC}"
echo -e "  Subscription: ${SUBSCRIPTION_NAME} (${SUBSCRIPTION_ID})"
echo -e "  Resource Group: ${RESOURCE_GROUP}"
echo -e "  Function App: ${FUNCTION_APP_NAME}"
echo -e "  Container Registry: ${ACR_NAME}"
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

# Get current account info
CURRENT_TENANT=$(az account show --query tenantId -o tsv)
CURRENT_SUBSCRIPTION=$(az account show --query id -o tsv)

echo -e "${GREEN}✓ Currently logged in${NC}"
echo -e "  Tenant: ${CURRENT_TENANT}"
echo -e "  Subscription: ${CURRENT_SUBSCRIPTION}"
echo ""

# Switch subscription if needed
if [ "$CURRENT_SUBSCRIPTION" != "$SUBSCRIPTION_ID" ]; then
    echo -e "${YELLOW}🔄 Switching to subscription: ${SUBSCRIPTION_ID}${NC}"
    az account set --subscription "$SUBSCRIPTION_ID"
    echo -e "${GREEN}✓ Subscription switched${NC}"
    echo ""
fi

# Login to Azure Container Registry
echo -e "${GREEN}🔑 Logging in to Azure Container Registry: ${ACR_NAME}${NC}"
az acr login --name "$ACR_NAME"
echo -e "${GREEN}✓ ACR login successful${NC}"
echo ""

# Build Docker image
FULL_IMAGE_NAME="${ACR_LOGIN_SERVER}/${FUNCTION_APP_NAME}:${IMAGE_TAG}"

CACHE_FLAG=""
if [ "$NO_CACHE" = true ]; then
    CACHE_FLAG="--no-cache"
    echo -e "${YELLOW}⚠️  Building without cache${NC}"
fi

echo -e "${GREEN}🔨 Building Docker image (linux/amd64)...${NC}"
echo -e "  Image: ${FULL_IMAGE_NAME}"
echo ""

docker build --platform linux/amd64 ${CACHE_FLAG} -t "$FULL_IMAGE_NAME" .

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Docker build failed!${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Docker image built successfully${NC}"
echo ""

# Push to Azure Container Registry
echo -e "${GREEN}📤 Pushing image to Azure Container Registry...${NC}"
docker push "$FULL_IMAGE_NAME"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Docker push failed!${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Image pushed successfully${NC}"
echo ""

# Exit if build-only mode
if [ "$BUILD_ONLY" = true ]; then
    echo -e "${YELLOW}⚠️  Build-only mode. Skipping deployment.${NC}"
    echo -e "${GREEN}✅ Build completed!${NC}"
    exit 0
fi

# Update Function App configuration
echo -e "${GREEN}🔄 Updating Function App configuration...${NC}"
az functionapp config container set \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --docker-custom-image-name "$FULL_IMAGE_NAME" \
    --docker-registry-server-url "https://${ACR_LOGIN_SERVER}"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Function App update failed!${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Function App configuration updated${NC}"
echo ""

# Restart Function App
echo -e "${GREEN}🔄 Restarting Function App...${NC}"
az functionapp restart \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$RESOURCE_GROUP"

echo ""
echo -e "${GREEN}✅ Deployment successful!${NC}"
echo ""
echo -e "${BLUE}📋 Function App Information:${NC}"
echo -e "  URL: https://${FUNCTION_APP_NAME}.azurewebsites.net"
echo -e "  Image: ${FULL_IMAGE_NAME}"
echo ""
echo -e "${BLUE}🔍 Useful commands:${NC}"
echo -e "  View logs:"
echo -e "    az webapp log tail --name ${FUNCTION_APP_NAME} --resource-group ${RESOURCE_GROUP}"
echo ""
echo -e "  Check status:"
echo -e "    az functionapp show --name ${FUNCTION_APP_NAME} --resource-group ${RESOURCE_GROUP} --query state"
echo ""
echo -e "  List functions:"
echo -e "    func azure functionapp list-functions ${FUNCTION_APP_NAME} --show-keys"
echo ""
