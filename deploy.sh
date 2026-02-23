#!/bin/bash
# Deploy Azure Function App
# Usage: ./deploy.sh

FUNCTION_APP_NAME="azfn-scg-dataprep"

echo "🚀 Deploying Azure Function: $FUNCTION_APP_NAME"
echo "================================================"
echo ""

# Check if logged in to Azure
echo "🔐 Checking Azure login..."
if ! az account show &> /dev/null; then
    echo "❌ Not logged in to Azure. Please run: az login"
    exit 1
fi

echo "✓ Azure login verified"
echo ""

# Deploy function app
echo "📦 Deploying function app..."
func azure functionapp publish "$FUNCTION_APP_NAME" --python

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Deployment successful!"
    echo ""
    echo "📋 Function URLs:"
    func azure functionapp list-functions "$FUNCTION_APP_NAME" --show-keys
    echo ""
    echo "🔍 To view logs, run:"
    echo "   func azure functionapp logstream $FUNCTION_APP_NAME"
else
    echo ""
    echo "❌ Deployment failed!"
    exit 1
fi
