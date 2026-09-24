# Azure Functions Data Preparation Service

A serverless Azure Functions application for processing and indexing documents using Azure AI Document Intelligence (Form Recognizer), Azure AI Search, and Azure OpenAI for advanced RAG (Retrieval Augmented Generation) scenarios.

## Features

- **Document Processing**: Extract text and structure from various document formats (PDF, images, Office documents)
- **Native Excel / CSV Ingestion**: Spreadsheets skip PDF/OCR; tables are converted to Markdown with merged headers preserved, chunked by row, and embedded images are OCR'd
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
- **PowerShell 7+** (for Windows users) - [Download](https://github.com/PowerShell/PowerShell/releases)

### Windows-Specific Requirements

If you're on Windows, make sure to:
1. Install **Windows Terminal** for better command-line experience
2. Run PowerShell as Administrator when installing tools
3. Enable long path support: `Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1`

### Required Azure Resources

You'll need to create the following Azure resources:

1. Azure Storage Account
2. Azure AI Document Intelligence (Form Recognizer)
3. Azure AI Search
4. Azure OpenAI Service
5. Azure Functions App (Linux, Python 3.9+)

## Windows Quick Start Guide

For Windows users, here's a streamlined setup process:

### 1. Install Prerequisites

**Install from Official Sources:**
- [Python 3.9+](https://www.python.org/downloads/) - Check "Add Python to PATH"
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli-windows) - Use MSI installer
- [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local) - via npm or MSI
- [Git for Windows](https://git-scm.com/download/win) - Includes Git Bash
- [PowerShell 7+](https://github.com/PowerShell/PowerShell/releases) - Optional but recommended

**Via Package Manager (Chocolatey):**
```powershell
# Install Chocolatey first from https://chocolatey.org
choco install python azure-cli git nodejs
npm install -g azure-functions-core-tools@4
```

**Via Package Manager (winget):**
```powershell
winget install Python.Python.3.11
winget install Microsoft.AzureCLI
winget install Git.Git
winget install OpenJS.NodeJS
npm install -g azure-functions-core-tools@4
```

### 2. Verify Installation

Open PowerShell and verify all tools:
```powershell
python --version
az --version
func --version
git --version
```

### 3. Key Windows Differences

| Aspect | Linux/Mac | Windows PowerShell |
|--------|-----------|-------------------|
| Line continuation | `\` | `` ` `` (backtick) |
| Virtual env activation | `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| Copy files | `cp file1 file2` | `Copy-Item file1 file2` |
| Variables | `$VAR` in bash | `$VAR` in PowerShell |
| Path separator | `/` | `\` |
| curl command | `curl` | `curl.exe` or `Invoke-RestMethod` |
| Shell scripts | `.sh` files run directly | Need Git Bash or convert to `.ps1` |

### 4. Recommended: Windows Terminal

Install Windows Terminal for better experience:
```powershell
winget install Microsoft.WindowsTerminal
```

Or from Microsoft Store.

## Quick Start - Local Development

### 1. Clone the Repository

**Linux/Mac:**
```bash
git clone https://github.com/theheronat/scg-advanced-rag.git
cd scg-advanced-rag
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/theheronat/scg-advanced-rag.git
cd scg-advanced-rag
```

### 2. Create Virtual Environment

**Linux/Mac:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Note for Windows:** If you get an execution policy error, run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 3. Configure Local Settings

Copy the local settings template and fill in your Azure credentials:

**Linux/Mac:**
```bash
cp local.settings.json.example local.settings.json
```

**Windows (PowerShell):**
```powershell
Copy-Item local.settings.json.example local.settings.json
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

> **Note for Windows Users:**
> - On Windows PowerShell, line continuation uses backtick `` ` `` instead of backslash `\`
> - Variables are accessed with `$variableName` instead of `"$variableName"`
> - Commands shown work the same way; only syntax differs slightly

### Step 1: Login to Azure

**Linux/Mac/Windows (same command):**
```bash
az login
az account set --subscription "your-subscription-id"
```

### Step 2: Create Resource Group

**Linux/Mac:**
```bash
az group create \
  --name "rg-scg-dataprep" \
  --location "eastus"
```

**Windows (PowerShell):**
```powershell
az group create `
  --name "rg-scg-dataprep" `
  --location "eastus"
```

### Step 3: Create Azure Storage Account

**Linux/Mac:**
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

**Windows (PowerShell):**
```powershell
az storage account create `
  --name "scgdataprepdemo" `
  --resource-group "rg-scg-dataprep" `
  --location "eastus" `
  --sku "Standard_LRS" `
  --kind "StorageV2"

# Get storage account key
$STORAGE_KEY = az storage account keys list `
  --account-name "scgdataprepdemo" `
  --resource-group "rg-scg-dataprep" `
  --query "[0].value" -o tsv

# Create container
az storage container create `
  --name "raw" `
  --account-name "scgdataprepdemo" `
  --account-key $STORAGE_KEY
```

### Step 4: Create Azure AI Document Intelligence

**Linux/Mac:**
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

**Windows (PowerShell):**
```powershell
az cognitiveservices account create `
  --name "scg-doc-intelligence" `
  --resource-group "rg-scg-dataprep" `
  --kind "FormRecognizer" `
  --sku "S0" `
  --location "eastus"

# Get endpoint and key
$DOC_INTELLIGENCE_ENDPOINT = az cognitiveservices account show `
  --name "scg-doc-intelligence" `
  --resource-group "rg-scg-dataprep" `
  --query "properties.endpoint" -o tsv

$DOC_INTELLIGENCE_KEY = az cognitiveservices account keys list `
  --name "scg-doc-intelligence" `
  --resource-group "rg-scg-dataprep" `
  --query "key1" -o tsv
```

### Step 5: Create Azure AI Search

**Linux/Mac:**
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

**Windows (PowerShell):**
```powershell
az search service create `
  --name "scg-search-demo" `
  --resource-group "rg-scg-dataprep" `
  --sku "basic" `
  --location "eastus"

# Get admin key
$SEARCH_KEY = az search admin-key show `
  --service-name "scg-search-demo" `
  --resource-group "rg-scg-dataprep" `
  --query "primaryKey" -o tsv
```

### Step 6: Create Azure OpenAI Service

**Linux/Mac:**
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

**Windows (PowerShell):**
```powershell
az cognitiveservices account create `
  --name "scg-openai-demo" `
  --resource-group "rg-scg-dataprep" `
  --kind "OpenAI" `
  --sku "S0" `
  --location "eastus"

# Deploy embedding model
az cognitiveservices account deployment create `
  --name "scg-openai-demo" `
  --resource-group "rg-scg-dataprep" `
  --deployment-name "text-embedding-3-large" `
  --model-name "text-embedding-3-large" `
  --model-version "1" `
  --model-format "OpenAI" `
  --sku-capacity 1 `
  --sku-name "Standard"

# Deploy chat model (optional, for document processing)
az cognitiveservices account deployment create `
  --name "scg-openai-demo" `
  --resource-group "rg-scg-dataprep" `
  --deployment-name "gpt-4o-mini" `
  --model-name "gpt-4o-mini" `
  --model-version "2024-07-18" `
  --model-format "OpenAI" `
  --sku-capacity 1 `
  --sku-name "Standard"

# Get endpoint and key
$OPENAI_ENDPOINT = az cognitiveservices account show `
  --name "scg-openai-demo" `
  --resource-group "rg-scg-dataprep" `
  --query "properties.endpoint" -o tsv

$OPENAI_KEY = az cognitiveservices account keys list `
  --name "scg-openai-demo" `
  --resource-group "rg-scg-dataprep" `
  --query "key1" -o tsv
```

### Step 7: Create Azure Function App

**Linux/Mac:**
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

**Windows (PowerShell):**
```powershell
# Create a storage account for the function app
az storage account create `
  --name "scgfunctionstorage" `
  --resource-group "rg-scg-dataprep" `
  --location "eastus" `
  --sku "Standard_LRS"

# Create Function App
az functionapp create `
  --resource-group "rg-scg-dataprep" `
  --consumption-plan-location "eastus" `
  --runtime "python" `
  --runtime-version "3.9" `
  --functions-version "4" `
  --name "azfn-scg-dataprep" `
  --storage-account "scgfunctionstorage" `
  --os-type "Linux"
```

### Step 8: Configure Application Settings

Create a deployment settings script:

**Linux/Mac:**
```bash
cp deploy_settings.sh.template deploy_settings.sh
# Edit deploy_settings.sh with your values, then run:
chmod +x deploy_settings.sh
./deploy_settings.sh
```

**Windows (PowerShell):**
```powershell
Copy-Item deploy_settings.sh.template deploy_settings.sh
# Edit deploy_settings.sh with your values, then run:
bash ./deploy_settings.sh
```

Or configure manually:

**Linux/Mac:**
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

**Windows (PowerShell):**
```powershell
az functionapp config appsettings set `
  --name "azfn-scg-dataprep" `
  --resource-group "rg-scg-dataprep" `
  --settings `
    AZURE_STORAGE_ACCOUNT_NAME="scgdataprepdemo" `
    AZURE_STORAGE_ACCOUNT_KEY="$STORAGE_KEY" `
    AZURE_STORAGE_CONTAINER="raw" `
    AZURE_FORM_RECOGNIZER_ENDPOINT="$DOC_INTELLIGENCE_ENDPOINT" `
    AZURE_FORM_RECOGNIZER_KEY="$DOC_INTELLIGENCE_KEY" `
    AZURE_SEARCH_ENDPOINT="https://scg-search-demo.search.windows.net" `
    AZURE_SEARCH_INDEX="scg-rag" `
    AZURE_SEARCH_KEY="$SEARCH_KEY" `
    AZURE_OPENAI_URL="$OPENAI_ENDPOINT" `
    AZURE_OPENAI_MODEL="gpt-4o-mini" `
    AZURE_OPENAI_API_VERSION="2025-01-01-preview" `
    AZURE_OPENAI_API_KEY="$OPENAI_KEY" `
    AZURE_OPENAI_EMBEDDING_MODEL="text-embedding-3-large"
```

### Step 9: Deploy the Function App

**Linux/Mac/Windows (same command):**
```bash
func azure functionapp publish azfn-scg-dataprep
```

### Step 10: Verify Deployment

**Linux/Mac:**
```bash
# Get function app URL
az functionapp show \
  --name "azfn-scg-dataprep" \
  --resource-group "rg-scg-dataprep" \
  --query "defaultHostName" -o tsv

# Test health endpoint
curl https://azfn-scg-dataprep.azurewebsites.net/api/health
```

**Windows (PowerShell):**
```powershell
# Get function app URL
az functionapp show `
  --name "azfn-scg-dataprep" `
  --resource-group "rg-scg-dataprep" `
  --query "defaultHostName" -o tsv

# Test health endpoint (using Invoke-WebRequest)
Invoke-WebRequest -Uri "https://azfn-scg-dataprep.azurewebsites.net/api/health"

# Or if curl is installed on Windows
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

## Excel & CSV Ingestion (native tabular path)

`ingest` routes spreadsheets away from the LibreOffice → PDF → OCR flow. The PDF/OCR flow for
`.pdf`, `.docx`, `.pptx`, and images is unchanged.

| Extension | Reader | Notes |
|---|---|---|
| `.xlsx`, `.xlsm` | `openpyxl` (normal mode, `data_only=True`) | formulas → cached values; merged cells, fonts, and images are read |
| `.xls` | `xlrd` (`formatting_info=True`) | merged cells + bold supported; embedded images are **not** extracted |
| `.csv`, `.tsv` | stdlib `csv` | encoding + delimiter auto-detected; values stay strings |

```
Excel/CSV → read cells → detect layout → Markdown/HTML tables → row-aware chunks
          → contextualize_batch → embed_batch → index_docs (batches of 100)
Excel images → upload to blob → Form Recognizer OCR (prebuilt-layout) → image chunk
```

**Layout detection (Excel).** Real workbooks rarely have "row 1 = header", so each visible sheet is split into:
- *bands*: a single merged or lone value outside a table. A band becomes the sheet title, a table title, or an image caption. Any other band goes into a per-sheet `notes` chunk, so no text is lost.
- *tables*: contiguous non-band rows. Header rows are the leading all-bold rows (up to 3). If a sheet has no styling, the header is the first row, extended downward while a merged cell groups sub-columns below it (two-level headers become `Group / Sub`).
- *key-value grids*: bold labels and plain values in alternating columns. These are rendered as a `Field | Value` table.
- Hidden sheets, empty columns, and duplicate columns created by horizontal merges are dropped. Dates are written as `YYYY-MM-DD`, `1000.0` becomes `1000`, and empty cells become `""`.

**Chunking.** Rows are never split. Every chunk starts with a context line
(`# Sheet: {sheet} — {sheet title} — {table title} — Columns: …` or `# File: {csv} — Columns: …`),
followed by the header row(s). `EXCEL_ROW_OVERLAP` rows carry over into the next chunk. A single row longer than
`MAX_SECTION_LENGTH` becomes its own chunk.

**Index mapping (no schema change).**

| Field | Excel | CSV |
|---|---|---|
| `section` | `{sheet}#chunk_{i}`, `{sheet}#image_{n}`, `{sheet}#notes` | `{basename}#chunk_{i}` |
| `page` | 1-based sheet position in the workbook | `1` |
| `block_type` | `table` / `image` / `paragraph` (notes) | `table` |
| `source_file` | original file name (e.g. `report.xlsx`, **not** `.pdf`) | original file name |
| `id` | `sanitize_document_id("{base}-{sheet}-{i}")` | `sanitize_document_id("{base}-{i}")` |

Names that contain non-ASCII characters (e.g. Thai sheet names) get a short SHA-1 suffix before sanitizing.
`sanitize_document_id` replaces every Thai character with `_`, so without the suffix all Thai sheet names would produce the same ID.
The image blob URL is stored inside `content` (`(image_url: …)`) because the index has no field for it.
Use `delete_by_source` with the original `.xlsx`/`.csv` name.

**Embedded images (Excel).** Images come from `ws._images`. If openpyxl exposes no images for a sheet (e.g. EMF/WMF), they are read from the
xlsx zip (`xl/media` via drawing rels) instead. Images smaller than `EXCEL_IMAGE_MIN_PX` or 1 KB are skipped, and GIFs and other formats are converted to PNG.
Each image is uploaded to `processed/images/{base}/{sheet}/{n}.{ext}` and OCR'd with the same Form Recognizer client as
`ocr_pdf`. Identical images are OCR'd once. If OCR fails for one image, it is logged and the image is indexed with its URL only.
Charts are counted and logged but not rasterized.

**CSV encoding / delimiter.** The encoder first tries `utf-8-sig`/`utf-8`, validated over the whole file. It then tries `cp874` when the decoded text is
mostly Thai characters, then `charset-normalizer`'s guess, then `tis-620`, and finally `latin-1`. Delimiter detection uses `csv.Sniffer` over `, ; \t |`
(`.tsv` always uses tab; the fallback is comma). Ragged rows are padded, and extra columns are kept as `Column N`.

**Environment flags**

| Variable | Default | Values |
|---|---|---|
| `EXCEL_TABLE_FORMAT` | `markdown` | `markdown` \| `html` (same `<table>` shape as OCR output) |
| `EXCEL_SAVE_PROCESSED_FORMAT` | `md` | `md` \| `html` \| `none`: readable copy saved to local `processed/` + blob `processed` (Excel and CSV) |
| `EXCEL_IMAGE_MODE` | `ocr_ref` | `ocr_ref` (upload + OCR + reference) \| `ref_only` (upload + reference) \| `none` |
| `EXCEL_IMAGE_MIN_PX` | `40` | minimum image width/height sent to OCR |
| `EXCEL_ROW_OVERLAP` | `1` | data rows repeated at the start of the next chunk |

For Excel/CSV, the response keeps the usual keys (`pdf_filename` is `null`; `local_path`/`blob_url` point to the processed `.md`/`.html`) and adds
`processed_filename`, `file_type`, and `block_types`.

**Self-check (offline, Azure calls mocked):**

```bash
python selfcheck_tabular.py accounting_knowledge_rag_demo.xlsx
```

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

**Linux/Mac:**
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

**Windows (PowerShell):**
```powershell
# Upload a document
curl.exe -X POST `
  -F "file=@document.pdf" `
  https://azfn-scg-dataprep.azurewebsites.net/api/upload

# Or using PowerShell native commands
$headers = @{
    "Content-Type" = "multipart/form-data"
}
$filePath = "C:\path\to\document.pdf"
$uri = "https://azfn-scg-dataprep.azurewebsites.net/api/upload"
Invoke-RestMethod -Uri $uri -Method Post -InFile $filePath -Headers $headers

# Process the document
curl.exe -X POST https://azfn-scg-dataprep.azurewebsites.net/api/process/document.pdf

# Check status
curl.exe https://azfn-scg-dataprep.azurewebsites.net/api/status/doc_12345
```

### Search Documents

**Linux/Mac:**
```bash
curl "https://azfn-scg-dataprep.azurewebsites.net/api/search?query=azure+functions"
```

**Windows (PowerShell):**
```powershell
# Using curl
curl.exe "https://azfn-scg-dataprep.azurewebsites.net/api/search?query=azure+functions"

# Or using PowerShell native command
Invoke-RestMethod -Uri "https://azfn-scg-dataprep.azurewebsites.net/api/search?query=azure+functions"
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

**Linux/Mac:**
```bash
# Stream logs
func azure functionapp logstream azfn-scg-dataprep

# Or via Azure CLI
az webapp log tail \
  --name "azfn-scg-dataprep" \
  --resource-group "rg-scg-dataprep"
```

**Windows (PowerShell):**
```powershell
# Stream logs
func azure functionapp logstream azfn-scg-dataprep

# Or via Azure CLI
az webapp log tail `
  --name "azfn-scg-dataprep" `
  --resource-group "rg-scg-dataprep"
```

### Common Issues

**Issue: Function timeout**
- Solution: Increase timeout in `host.json` or use Durable Functions for long-running processes

**Issue: Storage connection failed**
- Solution: Verify storage account credentials and network access

**Issue: OpenAI rate limits**
- Solution: Implement retry logic or increase quota

### Windows-Specific Troubleshooting

**Issue: PowerShell execution policy error**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Issue: Python not found**
- Ensure Python is added to PATH during installation
- Restart PowerShell after installing Python
- Verify: `python --version`

**Issue: Azure CLI line continuation**
- Use backtick `` ` `` (not backslash `\`) for multi-line commands
- Ensure no spaces after the backtick

**Issue: curl alias conflicts**
- PowerShell has a `curl` alias for `Invoke-WebRequest`
- Use `curl.exe` explicitly for the real curl command
- Or remove alias: `Remove-Item alias:curl`

**Issue: Bash scripts on Windows**
- Install Git Bash or WSL (Windows Subsystem for Linux)
- Or convert shell scripts to PowerShell equivalents

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
