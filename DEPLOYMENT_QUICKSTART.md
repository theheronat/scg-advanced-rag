# 🚀 Deployment Quick Start Guide

คู่มือสั้นๆ สำหรับ Deploy Azure Function ไปยังหลาย Environments

---

## ⚡ Quick Start (5 นาที)

### 1. ติดตั้ง Tools

```bash
brew install jq azure-cli
# เปิด Docker Desktop
```

### 2. กำหนดค่า Environment

แก้ไขไฟล์ `deploy-config.json`:

```json
{
  "environments": {
    "dev": {
      "tenant_id": "",                           // Optional
      "subscription_id": "YOUR_SUBSCRIPTION_ID",
      "resource_group": "YOUR_RESOURCE_GROUP",
      "function_app_name": "YOUR_FUNCTION_NAME",
      "acr_name": "YOUR_ACR_NAME",
      "acr_login_server": "YOUR_ACR_NAME.azurecr.io"
    }
  }
}
```

### 3. กำหนดค่า Settings

แก้ไขไฟล์ `settings-dev.json` ตามค่าจริงของคุณ

### 4. Deploy!

```bash
# Deploy environment variables
./deploy-settings-universal.sh dev

# Deploy Docker image
./docker-deploy-universal.sh dev
```

เสร็จแล้ว! ✅

---

## 📝 Commands ที่ใช้บ่อย

### Deploy to Different Environments

```bash
# Development
./docker-deploy-universal.sh dev

# Staging
./docker-deploy-universal.sh staging

# Production
./docker-deploy-universal.sh prod
```

### Deploy Options

```bash
# Build only (ไม่ deploy)
./docker-deploy-universal.sh dev --build-only

# Build without cache (ถ้ามีปัญหา)
./docker-deploy-universal.sh dev --no-cache

# Deploy with specific version tag
./docker-deploy-universal.sh prod --tag v1.2.3
```

### Update Settings เฉพาะ

```bash
# อัปเดต environment variables อย่างเดียว
./deploy-settings-universal.sh prod
```

---

## 🌐 Multi-Tenant Deployment

### สำหรับ Deploy ข้าม Tenants

1. **เพิ่ม Tenant ID** ใน `deploy-config.json`:
   ```json
   {
     "environments": {
       "client-a": {
         "tenant_id": "TENANT_A_ID",
         "subscription_id": "SUB_A_ID",
         ...
       },
       "client-b": {
         "tenant_id": "TENANT_B_ID",
         "subscription_id": "SUB_B_ID",
         ...
       }
     }
   }
   ```

2. **Deploy ไปยัง Client A:**
   ```bash
   ./docker-deploy-universal.sh client-a
   ```
   Script จะ login ไปยัง Tenant A อัตโนมัติ

3. **Deploy ไปยัง Client B:**
   ```bash
   ./docker-deploy-universal.sh client-b
   ```
   Script จะ switch ไปยัง Tenant B อัตโนมัติ

---

## 🔍 Monitoring

### ดู Logs

```bash
az webapp log tail \
  --name YOUR_FUNCTION_NAME \
  --resource-group YOUR_RESOURCE_GROUP
```

### ตรวจสอบ Status

```bash
az functionapp show \
  --name YOUR_FUNCTION_NAME \
  --resource-group YOUR_RESOURCE_GROUP \
  --query state
```

---

## 🆘 Troubleshooting

### Build ช้า (Apple Silicon)

เพิ่ม resources ใน Docker Desktop:
- Memory: 8GB+
- CPUs: 4+

### Authentication Error

```bash
az login --tenant YOUR_TENANT_ID
```

### Permission Denied

ตรวจสอบว่ามี role:
- **Contributor** ใน Resource Group
- **AcrPush** ใน Container Registry

---

## 📚 เอกสารเพิ่มเติม

- คำแนะนำแบบละเอียด: [MULTI_TENANT_DEPLOYMENT.md](MULTI_TENANT_DEPLOYMENT.md)
- Docker deployment: [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)
- API usage: [API_USAGE.md](API_USAGE.md)

---

## 🎯 สรุป

| Command | Description |
|---------|-------------|
| `./deploy-settings-universal.sh [env]` | Deploy environment variables |
| `./docker-deploy-universal.sh [env]` | Deploy Docker image |
| `./docker-deploy-universal.sh [env] --build-only` | Build เฉพาะ (ไม่ deploy) |
| `./docker-deploy-universal.sh [env] --no-cache` | Build without cache |
| `./docker-deploy-universal.sh [env] --tag v1.0` | Deploy with version tag |

---

**Next Steps:**
1. อ่านคำแนะนำแบบละเอียดใน [MULTI_TENANT_DEPLOYMENT.md](MULTI_TENANT_DEPLOYMENT.md)
2. ตั้งค่า CI/CD pipeline (GitHub Actions / Azure DevOps)
3. ใช้ Azure Key Vault สำหรับ secrets management
