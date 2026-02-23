# Azure Functions Data Preparation Service

A serverless Azure Functions application for processing and indexing documents using Azure AI Document Intelligence (Form Recognizer), Azure AI Search, and Azure OpenAI for advanced RAG (Retrieval Augmented Generation) scenarios.

## Features

- **Document Processing**: Extract text and structure from various document formats (PDF, images, Office documents)
- **Intelligent Chunking**: Smart document chunking with configurable overlap for optimal retrieval
- **Vector Embeddings**: Generate embeddings using Azure OpenAI for semantic search
- **Azure AI Search Integration**: Automatically index processed documents with metadata
- **Multi-Tenant Support**: Isolated data processing for multiple tenants
- **RESTful API**: HTTP endpoints for document upload, processing, and management
- **Docker Support**: Containerized deployment for consistent environments

## Architecture

```
Document Upload → Azure Storage → Azure Functions → Document Intelligence
                                         ↓
                                   Text Chunking
                                         ↓
                                  Azure OpenAI (Embeddings)
                                         ↓
                                  Azure AI Search (Indexing)
```

## Prerequisites

Before deploying, ensure you have:

- **Azure Subscription** with access to create resources
- **Azure CLI** installed ([Download](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli))
- **Python 3.9+** for local development
- **Azure Functions Core Tools** v4 ([Install](https://docs.microsoft.com/en-us/azure/azure-functions/functions-run-local))
- **Git** for version control

### Required Azure Resources

You'll need to create the following Azure resources:

1. Azure Storage Account
2. Azure AI Document Intelligence (Form Recognizer)
3. Azure AI Search
4. Azure OpenAI Service
5. Azure Functions App (Linux, Python 3.9+)

## Quick Start - Local Development

### 1. Clone the Repository

```bash
git clone https://github.com/theheronat/scg-advanced-rag.git
cd scg-advanced-rag
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Local Settings

Copy the local settings template and fill in your Azure credentials:

```bash
cp local.settings.json.example local.settings.json
```

Edit `local.settings.json`:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AZURE_STORAGE_ACCOUNT_NAME": "your-storage-account",
    "AZURE_STORAGE_ACCOUNT_KEY": "your-storage-key",
    "AZURE_STORAGE_CONTAINER": "raw",
    "AZURE_FORM_RECOGNIZER_ENDPOINT": "https://your-instance.cognitiveservices.azure.com",
    "AZURE_FORM_RECOGNIZER_KEY": "your-key",
    "AZURE_SEARCH_ENDPOINT": "https://your-search.search.windows.net",
    "AZURE_SEARCH_INDEX": "your-index-name",
    "AZURE_SEARCH_KEY": "your-search-key",
    "AZURE_OPENAI_URL": "https://your-openai.cognitiveservices.azure.com/",
    "AZURE_OPENAI_MODEL": "gpt-4o-mini",
    "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
    "AZURE_OPENAI_API_KEY": "your-openai-key",
    "AZURE_OPENAI_EMBEDDING_MODEL": "text-embedding-3-large"
  }
}
```

### 4. Run Locally

```bash
func start
```

The API will be available at `http://localhost:7071`

## Azure Deployment - Step by Step

### Step 1: Login to Azure

```bash
az login
az account set --subscription "your-subscription-id"
```

### Step 2: Create Resource Group

```bash
az group create \
  --name "rg-scg-dataprep" \
  --location "eastus"
```

### Step 3: Create Azure Storage Account

```bash
az storage account create \
  --name "scgdataprepdemo" \
  --resource-group "rg-scg-dataprep" \
  --location "eastus" \
  --sku "Standard_LRS" \
  --kind "StorageV2"

# Get storage account key
STORAGE_KEY=$(az storage account keys list \
  --account-name "scgdataprepdemo" \
  --resource-group "rg-scg-dataprep" \
  --query "[0].value" -o tsv)

# Create container
az storage container create \
  --name "raw" \
  --account-name "scgdataprepdemo" \
  --account-key "$STORAGE_KEY"
```

### Step 4: Create Azure AI Document Intelligence

```bash
az cognitiveservices account create \
  --name "scg-doc-intelligence" \
  --resource-group "rg-scg-dataprep" \
  --kind "FormRecognizer" \
  --sku "S0" \
  --location "eastus"

# Get endpoint and key
DOC_INTELLIGENCE_ENDPOINT=$(az cognitiveservices account show \
  --name "scg-doc-intelligence" \
  --resource-group "rg-scg-dataprep" \
  --query "properties.endpoint" -o tsv)

DOC_INTELLIGENCE_KEY=$(az cognitiveservices account keys list \
  --name "scg-doc-intelligence" \
  --resource-group "rg-scg-dataprep" \
  --query "key1" -o tsv)
```

### Step 5: Create Azure AI Search

```bash
az search service create \
  --name "scg-search-demo" \
  --resource-group "rg-scg-dataprep" \
  --sku "basic" \
  --location "eastus"

# Get admin key
SEARCH_KEY=$(az search admin-key show \
  --service-name "scg-search-demo" \
  --resource-group "rg-scg-dataprep" \
  --query "primaryKey" -o tsv)
```

### Step 6: Create Azure OpenAI Service

```bash
az cognitiveservices account create \
  --name "scg-openai-demo" \
  --resource-group "rg-scg-dataprep" \
  --kind "OpenAI" \
  --sku "S0" \
  --location "eastus"

# Deploy embedding model
az cognitiveservices account deployment create \
  --name "scg-openai-demo" \
  --resource-group "rg-scg-dataprep" \
  --deployment-name "text-embedding-3-large" \
  --model-name "text-embedding-3-large" \
  --model-version "1" \
  --model-format "OpenAI" \
  --sku-capacity 1 \
  --sku-name "Standard"

# Deploy chat model (optional, for document processing)
az cognitiveservices account deployment create \
  --name "scg-openai-demo" \
  --resource-group "rg-scg-dataprep" \
  --deployment-name "gpt-4o-mini" \
  --model-name "gpt-4o-mini" \
  --model-version "2024-07-18" \
  --model-format "OpenAI" \
  --sku-capacity 1 \
  --sku-name "Standard"

# Get endpoint and key
OPENAI_ENDPOINT=$(az cognitiveservices account show \
  --name "scg-openai-demo" \
  --resource-group "rg-scg-dataprep" \
  --query "properties.endpoint" -o tsv)

OPENAI_KEY=$(az cognitiveservices account keys list \
  --name "scg-openai-demo" \
  --resource-group "rg-scg-dataprep" \
  --query "key1" -o tsv)
```

### Step 7: Create Azure Function App

```bash
# Create a storage account for the function app
az storage account create \
  --name "scgfunctionstorage" \
  --resource-group "rg-scg-dataprep" \
  --location "eastus" \
  --sku "Standard_LRS"

# Create Function App
az functionapp create \
  --resource-group "rg-scg-dataprep" \
  --consumption-plan-location "eastus" \
  --runtime "python" \
  --runtime-version "3.9" \
  --functions-version "4" \
  --name "azfn-scg-dataprep" \
  --storage-account "scgfunctionstorage" \
  --os-type "Linux"
```

### Step 8: Configure Application Settings

Create a deployment settings script:

```bash
cp deploy_settings.sh.template deploy_settings.sh
```

Edit `deploy_settings.sh` with your values, then run:

```bash
chmod +x deploy_settings.sh
./deploy_settings.sh
```

Or configure manually:

```bash
az functionapp config appsettings set \
  --name "azfn-scg-dataprep" \
  --resource-group "rg-scg-dataprep" \
  --settings \
    AZURE_STORAGE_ACCOUNT_NAME="scgdataprepdemo" \
    AZURE_STORAGE_ACCOUNT_KEY="$STORAGE_KEY" \
    AZURE_STORAGE_CONTAINER="raw" \
    AZURE_FORM_RECOGNIZER_ENDPOINT="$DOC_INTELLIGENCE_ENDPOINT" \
    AZURE_FORM_RECOGNIZER_KEY="$DOC_INTELLIGENCE_KEY" \
    AZURE_SEARCH_ENDPOINT="https://scg-search-demo.search.windows.net" \
    AZURE_SEARCH_INDEX="scg-rag" \
    AZURE_SEARCH_KEY="$SEARCH_KEY" \
    AZURE_OPENAI_URL="$OPENAI_ENDPOINT" \
    AZURE_OPENAI_MODEL="gpt-4o-mini" \
    AZURE_OPENAI_API_VERSION="2025-01-01-preview" \
    AZURE_OPENAI_API_KEY="$OPENAI_KEY" \
    AZURE_OPENAI_EMBEDDING_MODEL="text-embedding-3-large"
```

### Step 9: Deploy the Function App

```bash
func azure functionapp publish azfn-scg-dataprep
```

### Step 10: Verify Deployment

```bash
# Get function app URL
az functionapp show \
  --name "azfn-scg-dataprep" \
  --resource-group "rg-scg-dataprep" \
  --query "defaultHostName" -o tsv

# Test health endpoint
curl https://azfn-scg-dataprep.azurewebsites.net/api/health
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": "2026-02-23T12:00:00Z",
  "version": "1.0.0"
}
```

## Alternative Deployment Methods

### Docker Deployment

See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for containerized deployment.

```bash
# Build and deploy with Docker
chmod +x docker-deploy.sh
./docker-deploy.sh
```

### Multi-Tenant Deployment

See [MULTI_TENANT_DEPLOYMENT.md](MULTI_TENANT_DEPLOYMENT.md) for deploying multiple isolated instances.

## API Endpoints

Once deployed, the following endpoints are available:

### Document Processing

- `POST /api/upload` - Upload a document for processing
- `POST /api/process/{filename}` - Process a specific document
- `GET /api/status/{document_id}` - Check processing status
- `DELETE /api/documents/{document_id}` - Delete a document and its chunks

### Health & Management

- `GET /api/health` - Health check endpoint
- `GET /api/documents` - List all processed documents
- `GET /api/search?query={text}` - Search indexed documents

For detailed API documentation, see [API_USAGE.md](API_USAGE.md).

## Example Usage

### Upload and Process a Document

```bash
# Upload a document
curl -X POST \
  -F "file=@document.pdf" \
  https://azfn-scg-dataprep.azurewebsites.net/api/upload

# Response
{
  "message": "File uploaded successfully",
  "filename": "document.pdf",
  "document_id": "doc_12345"
}

# Process the document
curl -X POST \
  https://azfn-scg-dataprep.azurewebsites.net/api/process/document.pdf

# Check status
curl https://azfn-scg-dataprep.azurewebsites.net/api/status/doc_12345
```

### Search Documents

```bash
curl "https://azfn-scg-dataprep.azurewebsites.net/api/search?query=azure+functions"
```

## Configuration Options

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AZURE_STORAGE_ACCOUNT_NAME` | Storage account name | Yes |
| `AZURE_STORAGE_ACCOUNT_KEY` | Storage account access key | Yes |
| `AZURE_STORAGE_CONTAINER` | Container for raw documents | Yes |
| `AZURE_FORM_RECOGNIZER_ENDPOINT` | Document Intelligence endpoint | Yes |
| `AZURE_FORM_RECOGNIZER_KEY` | Document Intelligence key | Yes |
| `AZURE_SEARCH_ENDPOINT` | Azure AI Search endpoint | Yes |
| `AZURE_SEARCH_INDEX` | Search index name | Yes |
| `AZURE_SEARCH_KEY` | Search admin key | Yes |
| `AZURE_OPENAI_URL` | Azure OpenAI endpoint | Yes |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | Yes |
| `AZURE_OPENAI_EMBEDDING_MODEL` | Embedding model deployment name | Yes |
| `AZURE_OPENAI_MODEL` | Chat model deployment name | No |

## Monitoring and Troubleshooting

### View Logs

```bash
# Stream logs
func azure functionapp logstream azfn-scg-dataprep

# Or via Azure CLI
az webapp log tail \
  --name "azfn-scg-dataprep" \
  --resource-group "rg-scg-dataprep"
```

### Common Issues

**Issue: Function timeout**
- Solution: Increase timeout in `host.json` or use Durable Functions for long-running processes

**Issue: Storage connection failed**
- Solution: Verify storage account credentials and network access

**Issue: OpenAI rate limits**
- Solution: Implement retry logic or increase quota

## Cost Estimation

Approximate monthly costs for moderate usage:

- Azure Functions: ~$20 (Consumption plan)
- Azure Storage: ~$5 (10GB storage)
- Document Intelligence: ~$50 (1000 pages)
- Azure AI Search: ~$75 (Basic tier)
- Azure OpenAI: ~$100 (varies by usage)

**Total: ~$250/month**

## Security Best Practices

1. **Never commit secrets** - Use Azure Key Vault or environment variables
2. **Enable HTTPS only** - Configure in Azure Portal
3. **Use Managed Identity** - Replace keys with managed identity where possible
4. **Enable CORS properly** - Restrict allowed origins
5. **Monitor access logs** - Enable Application Insights

## Documentation

- [API Usage Guide](API_USAGE.md)
- [Docker Deployment](DOCKER_DEPLOYMENT.md)
- [Multi-Tenant Deployment](MULTI_TENANT_DEPLOYMENT.md)
- [Quick Start Guide](DEPLOYMENT_QUICKSTART.md)
- [Index Structure](INDEX_STRUCTURE.md)
- [Change Log](CHANGES.md)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:
- GitHub Issues: [Create an issue](https://github.com/theheronat/scg-advanced-rag/issues)
- Email: support@example.com

## Acknowledgments

Built with:
- [Azure Functions](https://azure.microsoft.com/services/functions/)
- [Azure AI Document Intelligence](https://azure.microsoft.com/services/form-recognizer/)
- [Azure AI Search](https://azure.microsoft.com/services/search/)
- [Azure OpenAI](https://azure.microsoft.com/services/openai/)
