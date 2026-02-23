#!/bin/bash
# Build and Deploy Azure Function with Docker
# Usage: ./docker-deploy.sh

set -e

FUNCTION_APP_NAME="azfn-scg-dataprep"
RESOURCE_GROUP="BMG-OpenAI"
ACR_NAME="bmgcontainer"
IMAGE_NAME="azfn-scg-dataprep"
TAG="latest"

echo "🐳 Building and Deploying Docker Container to Azure Function"
echo "============================================================"
echo ""

# Check if logged in to Azure
echo "🔐 Checking Azure login..."
if ! az account show &> /dev/null; then
    echo "❌ Not logged in to Azure. Please run: az login"
    exit 1
fi

echo "✓ Azure login verified"
echo ""

# Login to Azure Container Registry
echo "🔑 Logging in to Azure Container Registry: $ACR_NAME..."
az acr login --name "$ACR_NAME"
echo "✓ ACR login successful"
echo ""

# Build Docker image
echo "🔨 Building Docker image (linux/amd64 for Azure)..."
FULL_IMAGE_NAME="$ACR_NAME.azurecr.io/$IMAGE_NAME:$TAG"

# Build for AMD64 platform (Azure Functions runs on AMD64)
docker build --platform linux/amd64 -t "$FULL_IMAGE_NAME" .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed!"
    exit 1
fi

echo "✓ Docker image built: $FULL_IMAGE_NAME"
echo ""

# Push to Azure Container Registry
echo "📤 Pushing image to Azure Container Registry..."
docker push "$FULL_IMAGE_NAME"

if [ $? -ne 0 ]; then
    echo "❌ Docker push failed!"
    exit 1
fi

echo "✓ Image pushed successfully"
echo ""

# Update Function App to use the new image
echo "🔄 Updating Function App configuration..."
az functionapp config container set \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --docker-custom-image-name "$FULL_IMAGE_NAME" \
    --docker-registry-server-url "https://$ACR_NAME.azurecr.io"

if [ $? -ne 0 ]; then
    echo "❌ Function App update failed!"
    exit 1
fi

echo "✓ Function App updated"
echo ""

# Restart Function App
echo "🔄 Restarting Function App..."
az functionapp restart \
    --name "$FUNCTION_APP_NAME" \
    --resource-group "$RESOURCE_GROUP"

echo ""
echo "✅ Deployment successful!"
echo ""
echo "📋 Function App URL:"
echo "   https://$FUNCTION_APP_NAME.azurewebsites.net"
echo ""
echo "🔍 To view logs, run:"
echo "   az webapp log tail --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP"
echo ""
echo "📊 To check deployment status:"
echo "   az functionapp show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP --query state"
