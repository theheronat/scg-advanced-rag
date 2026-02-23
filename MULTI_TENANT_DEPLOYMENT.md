# 🌐 Multi-Tenant / Multi-Subscription Deployment Guide

คู่มือสำหรับ Deploy Azure Function ไปยังหลาย Tenants และหลาย Subscriptions

---

## 📋 ไฟล์ที่เกี่ยวข้อง

```
azfn-scg-dataprep/
├── deploy-config.json              # กำหนดค่า environments
├── settings-dev.json               # Environment variables สำหรับ dev
├── settings-staging.json           # Environment variables สำหรับ staging
├── settings-prod.json              # Environment variables สำหรับ prod
├── docker-deploy-universal.sh      # Deploy Docker image
└── deploy-settings-universal.sh    # Deploy environment variables
```

---

## 🚀 ขั้นตอนการตั้งค่า

### ขั้นตอนที่ 1: ติดตั้ง Dependencies

```bash
# Install jq (JSON processor)
brew install jq

# Install Docker Desktop
# Download from: https://www.docker.com/products/docker-desktop

# Install Azure CLI
brew install azure-cli
```

### ขั้นตอนที่ 2: กำหนดค่า Environments

แก้ไขไฟล์ [deploy-config.json](deploy-config.json):

```json
{
  "environments": {
    "dev": {
      "tenant_id": "YOUR_DEV_TENANT_ID",           // Optional: ถ้าไม่ระบุจะใช้ default tenant
      "subscription_id": "xxx-xxx-xxx-xxx-xxx",
      "subscription_name": "Dev Subscription",
      "resource_group": "rg-dev",
      "function_app_name": "func-app-dev",
      "acr_name": "acrdev",
      "acr_login_server": "acrdev.azurecr.io",
      "location": "Southeast Asia"
    },
    "staging": {
      "tenant_id": "YOUR_STAGING_TENANT_ID",       // สำหรับ tenant อื่น
      "subscription_id": "yyy-yyy-yyy-yyy-yyy",
      "subscription_name": "Staging Subscription",
      "resource_group": "rg-staging",
      "function_app_name": "func-app-staging",
      "acr_name": "acrstaging",
      "acr_login_server": "acrstaging.azurecr.io",
      "location": "Southeast Asia"
    },
    "prod": {
      "tenant_id": "YOUR_PROD_TENANT_ID",          // อีก tenant หนึ่ง
      "subscription_id": "zzz-zzz-zzz-zzz-zzz",
      "subscription_name": "Production Subscription",
      "resource_group": "rg-prod",
      "function_app_name": "func-app-prod",
      "acr_name": "acrprod",
      "acr_login_server": "acrprod.azurecr.io",
      "location": "Southeast Asia"
    }
  }
}
```

### ขั้นตอนที่ 3: กำหนดค่า Environment Variables

แก้ไขไฟล์ settings สำหรับแต่ละ environment:

**Development**: [settings-dev.json](settings-dev.json)
```json
{
  "AZURE_STORAGE_ACCOUNT_NAME": "devstorageaccount",
  "AZURE_STORAGE_ACCOUNT_KEY": "dev_key_here",
  "AZURE_STORAGE_CONTAINER": "raw",
  "AZURE_FORM_RECOGNIZER_ENDPOINT": "https://dev-formrecognizer.cognitiveservices.azure.com",
  "AZURE_FORM_RECOGNIZER_KEY": "dev_key",
  "AZURE_SEARCH_ENDPOINT": "https://dev-search.search.windows.net",
  "AZURE_SEARCH_INDEX": "scg-rag-dev",
  "AZURE_SEARCH_KEY": "dev_search_key",
  "AZURE_OPENAI_URL": "https://dev-openai.cognitiveservices.azure.com/",
  "AZURE_OPENAI_MODEL": "gpt-4o-mini",
  "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
  "AZURE_OPENAI_API_KEY": "dev_openai_key",
  "AZURE_OPENAI_EMBEDDING_MODEL": "text-embedding-3-large"
}
```

**Staging**: [settings-staging.json](settings-staging.json) - แก้ไขตามของจริง

**Production**: [settings-prod.json](settings-prod.json) - แก้ไขตามของจริง

---

## 🔧 วิธีใช้งาน

### 1. Deploy Environment Variables

Deploy settings ก่อน (ต้องทำเพียงครั้งเดียว หรือเมื่อมีการเปลี่ยนแปลง):

```bash
# Deploy to Dev
./deploy-settings-universal.sh dev

# Deploy to Staging
./deploy-settings-universal.sh staging

# Deploy to Production
./deploy-settings-universal.sh prod
```

### 2. Deploy Docker Container

Deploy code และ Docker image:

```bash
# Deploy to Dev
./docker-deploy-universal.sh dev

# Deploy to Staging
./docker-deploy-universal.sh staging

# Deploy to Production
./docker-deploy-universal.sh prod
```

### 3. Deploy Options

Script รองรับ options หลายแบบ:

```bash
# Build เฉพาะ (ไม่ deploy)
./docker-deploy-universal.sh dev --build-only

# Build without cache
./docker-deploy-universal.sh prod --no-cache

# Deploy ด้วย custom tag
./docker-deploy-universal.sh prod --tag v1.2.3

# รวม options หลายตัว
./docker-deploy-universal.sh staging --no-cache --tag release-2024-02
```

---

## 🔐 การจัดการ Multi-Tenant

### สถานการณ์ที่ 1: ย้าย Environment ไปยัง Tenant ใหม่

ถ้าต้องการย้าย environment ไปยัง Azure AD Tenant ใหม่:

1. **ดึง Tenant ID จาก Azure Portal:**
   - ไปที่ Azure Portal → Azure Active Directory → Properties
   - Copy **Tenant ID**

2. **อัปเดต deploy-config.json:**
   ```json
   {
     "environments": {
       "prod": {
         "tenant_id": "NEW_TENANT_ID_HERE",
         "subscription_id": "NEW_SUBSCRIPTION_ID",
         ...
       }
     }
   }
   ```

3. **Login และ Deploy:**
   ```bash
   # Script จะ login ไปยัง tenant ใหม่อัตโนมัติ
   ./docker-deploy-universal.sh prod
   ```

### สถานการณ์ที่ 2: Deploy ไปหลาย Subscriptions ภายใน Tenant เดียว

ถ้าใช้ Tenant เดียวกันแต่คนละ Subscription:

```json
{
  "environments": {
    "dev": {
      "tenant_id": "",  // ปล่อยว่างไว้ หรือ ระบุ tenant เดียวกัน
      "subscription_id": "dev-subscription-id",
      ...
    },
    "prod": {
      "tenant_id": "",  // ปล่อยว่างไว้ หรือ ระบุ tenant เดียวกัน
      "subscription_id": "prod-subscription-id",
      ...
    }
  }
}
```

Script จะ switch subscription อัตโนมัติ

### สถานการณ์ที่ 3: Deploy ข้าม Organizations

เหมาะสำหรับ:
- Partner deployments
- Client deployments
- Multi-organization setups

```json
{
  "environments": {
    "client-a": {
      "tenant_id": "CLIENT_A_TENANT_ID",
      "subscription_id": "CLIENT_A_SUBSCRIPTION",
      "function_app_name": "func-client-a",
      ...
    },
    "client-b": {
      "tenant_id": "CLIENT_B_TENANT_ID",
      "subscription_id": "CLIENT_B_SUBSCRIPTION",
      "function_app_name": "func-client-b",
      ...
    }
  }
}
```

---

## 🔍 Troubleshooting

### 1. Authentication Error

```
ERROR: Please run 'az login' to setup account.
```

**แก้ไข:**
```bash
# Login with specific tenant
az login --tenant YOUR_TENANT_ID

# หรือ login แบบ interactive
az login
```

### 2. Subscription Not Found

```
ERROR: Subscription 'xxx' not found.
```

**แก้ไข:**
```bash
# List available subscriptions
az account list --output table

# Set correct subscription
az account set --subscription "YOUR_SUBSCRIPTION_ID"
```

### 3. Permission Denied

```
ERROR: You do not have authorization to perform action
```

**ตรวจสอบ:**
- ต้องมี **Contributor** role ใน Resource Group
- ต้องมี **AcrPush** role ใน Container Registry
- ต้องมี permission ใน Subscription

**แก้ไข:**
```bash
# Grant Contributor role
az role assignment create \
  --assignee user@example.com \
  --role Contributor \
  --resource-group YOUR_RESOURCE_GROUP

# Grant ACR Push role
az role assignment create \
  --assignee user@example.com \
  --role AcrPush \
  --scope /subscriptions/YOUR_SUB/resourceGroups/YOUR_RG/providers/Microsoft.ContainerRegistry/registries/YOUR_ACR
```

### 4. Docker Build เกิน Memory

บน **Apple Silicon (M1/M2/M3)** การ build linux/amd64 อาจช้า:

**วิธีแก้ที่ 1**: เพิ่ม Docker Resources
- เปิด Docker Desktop → Settings → Resources
- เพิ่ม Memory เป็น 8GB+
- เพิ่ม CPUs เป็น 4+

**วิธีแก้ที่ 2**: Build on Azure DevOps/GitHub Actions
- ใช้ CI/CD pipeline แทน local build
- เร็วกว่าและไม่กิน resources เครื่อง local

---

## 🔄 CI/CD Integration

### GitHub Actions Example

สร้างไฟล์ `.github/workflows/deploy-prod.yml`:

```yaml
name: Deploy to Production

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}

      - name: Deploy Settings
        run: ./deploy-settings-universal.sh prod

      - name: Deploy Docker
        run: ./docker-deploy-universal.sh prod --tag ${{ github.sha }}
```

### Azure DevOps Pipeline Example

สร้างไฟล์ `azure-pipelines.yml`:

```yaml
trigger:
  branches:
    include:
      - main

pool:
  vmImage: 'ubuntu-latest'

steps:
  - task: AzureCLI@2
    inputs:
      azureSubscription: 'Production Service Connection'
      scriptType: 'bash'
      scriptLocation: 'inlineScript'
      inlineScript: |
        ./deploy-settings-universal.sh prod
        ./docker-deploy-universal.sh prod --tag $(Build.BuildId)
```

---

## 📊 Monitoring และ Logging

### ดู Logs แบบ Real-time

```bash
# Development
az webapp log tail \
  --name func-app-dev \
  --resource-group rg-dev

# Production
az webapp log tail \
  --name func-app-prod \
  --resource-group rg-prod
```

### ตรวจสอบ Deployment Status

```bash
# Check Function App state
az functionapp show \
  --name func-app-prod \
  --resource-group rg-prod \
  --query state

# List all functions
func azure functionapp list-functions func-app-prod --show-keys
```

---

## ✅ Best Practices

### 1. ใช้ Separate Subscriptions

แนะนำให้แยก subscription ตาม environment:
- **Dev**: Subscription สำหรับ development
- **Staging**: Subscription สำหรับ testing
- **Prod**: Subscription สำหรับ production

### 2. ใช้ Key Vault สำหรับ Secrets

แทนที่จะเก็บ secrets ใน settings files:

```bash
# Store secrets in Key Vault
az keyvault secret set \
  --vault-name prod-keyvault \
  --name "OpenAI-ApiKey" \
  --value "your-secret-key"

# Reference in Function App
az functionapp config appsettings set \
  --name func-app-prod \
  --resource-group rg-prod \
  --settings "AZURE_OPENAI_API_KEY=@Microsoft.KeyVault(SecretUri=https://prod-keyvault.vault.azure.net/secrets/OpenAI-ApiKey/)"
```

### 3. ใช้ Managed Identity

แนะนำให้ใช้ Managed Identity แทน API Keys:

```bash
# Enable System Managed Identity
az functionapp identity assign \
  --name func-app-prod \
  --resource-group rg-prod

# Grant permissions
az role assignment create \
  --assignee MANAGED_IDENTITY_PRINCIPAL_ID \
  --role "Storage Blob Data Contributor" \
  --scope /subscriptions/SUB_ID/resourceGroups/RG/providers/Microsoft.Storage/storageAccounts/STORAGE
```

### 4. Tag Resources

ใช้ tags เพื่อจัดการ resources:

```bash
az functionapp update \
  --name func-app-prod \
  --resource-group rg-prod \
  --set tags.Environment=Production tags.ManagedBy=DevOps tags.CostCenter=IT
```

### 5. Version Control Settings Files

**ห้าม commit secrets ลง Git!**

สร้าง `.gitignore`:
```
settings-*.json
deploy-config.json
local.settings.json
.env
```

ใช้ templates แทน:
```
settings-dev.json.template
settings-prod.json.template
```

---

## 🆘 Support

หากพบปัญหา:

1. ตรวจสอบ logs: `az webapp log tail ...`
2. ตรวจสอบ configuration: `az functionapp config appsettings list ...`
3. ตรวจสอบ permissions: `az role assignment list ...`
4. ลอง redeploy settings: `./deploy-settings-universal.sh [env]`

---

## 📚 Resources

- [Azure Functions Documentation](https://learn.microsoft.com/en-us/azure/azure-functions/)
- [Azure Container Registry](https://learn.microsoft.com/en-us/azure/container-registry/)
- [Azure Multi-Tenant Applications](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/overview)
- [Azure CLI Reference](https://learn.microsoft.com/en-us/cli/azure/)
