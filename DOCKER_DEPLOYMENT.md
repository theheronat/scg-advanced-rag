# 🐳 Docker Deployment Guide

## ทำไมต้องใช้ Docker?

Azure Function แบบปกติ (Zip deployment) **ไม่มี LibreOffice** ติดตั้ง ทำให้ไม่สามารถแปลง:
- ❌ `.docx` → PDF
- ❌ `.xlsx` → PDF
- ❌ `.pptx` → PDF

**Docker Container** จะติดตั้ง LibreOffice พร้อม dependencies ทั้งหมด

---

## 📋 สิ่งที่ต้องมี

1. **Docker Desktop** ติดตั้งและรันอยู่

   **Linux/Mac:**
   ```bash
   docker --version
   ```

   **Windows (PowerShell):**
   ```powershell
   docker --version
   ```

2. **Azure CLI** login แล้ว

   **Linux/Mac:**
   ```bash
   az account show
   ```

   **Windows (PowerShell):**
   ```powershell
   az account show
   ```

3. **Azure Container Registry**: `bmgcontainer` (มีอยู่แล้ว)

4. **Function App**: `azfn-scg-dataprep` ต้องตั้งค่าเป็น **Container mode**

> **หมายเหตุสำหรับผู้ใช้ Windows:**
> - ใช้ PowerShell 7+ (แนะนำ) หรือ Command Prompt
> - ติดตั้ง Docker Desktop for Windows จาก [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)
> - ควรเปิดใช้งาน WSL 2 backend สำหรับ Docker
> - ใช้ backtick `` ` `` สำหรับ line continuation ใน PowerShell

---

## 🚀 ขั้นตอนการ Deploy

### ขั้นตอนที่ 1: ตั้งค่า Environment Variables

ใช้ Azure Portal หรือรัน script:

```bash
./deploy_settings.sh
```

### ขั้นตอนที่ 2: เปลี่ยน Function App เป็น Container Mode

ใน Azure Portal:
1. ไปที่ Function App → **azfn-scg-dataprep**
2. เลือก **Deployment Center**
3. เลือก **Container Registry**
4. ตั้งค่า:
   - **Registry**: Azure Container Registry → `bmgcontainer`
   - **Image**: จะถูกตั้งค่าโดย script (ขั้นตอนถัดไป)
   - **Authentication**: Admin Credentials หรือ Managed Identity

**หรือใช้ CLI:**

```bash
az functionapp config container set \
  --name azfn-scg-dataprep \
  --resource-group BMG-OpenAI \
  --enable-app-service-storage false
```

### ขั้นตอนที่ 3: Build และ Deploy Docker Image

```bash
./docker-deploy.sh
```

Script นี้จะ:
1. ✅ Login เข้า Azure Container Registry
2. ✅ Build Docker image (มี Python + LibreOffice)
3. ✅ Push image ไปที่ `bmgcontainer.azurecr.io`
4. ✅ อัปเดต Function App ให้ใช้ image ใหม่
5. ✅ Restart Function App

---

## 🔍 ตรวจสอบการ Deploy

### ดู Deployment Status

```bash
az functionapp show \
  --name azfn-scg-dataprep \
  --resource-group BMG-OpenAI \
  --query state
```

### ดู Logs แบบ Real-time

```bash
az webapp log tail \
  --name azfn-scg-dataprep \
  --resource-group BMG-OpenAI
```

### ทดสอบ Function

```bash
curl -X POST https://azfn-scg-dataprep.azurewebsites.net/api/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "blob_url": "https://scgaidata.blob.core.windows.net/raw/test.pdf",
    "category": "test"
  }'
```

---

## 📦 โครงสร้างไฟล์

```
azfn-scg-dataprep/
├── Dockerfile              # Docker image definition
├── .dockerignore          # Files to exclude from Docker build
├── docker-deploy.sh       # Build & deploy script
├── deploy_settings.sh     # Deploy environment variables
├── function_app.py        # Main function code
├── requirements.txt       # Python dependencies
├── host.json             # Function host configuration
└── local.settings.json   # Local development settings
```

---

## 🐛 Troubleshooting

### 1. Docker build ช้า

**สาเหตุ**: LibreOffice package ใหญ่ (~200MB)

**แก้ไข**: ใช้ multi-stage build (อัปเดต Dockerfile)

### 2. Function App ไม่ start

**ตรวจสอบ**:
```bash
az webapp log tail \
  --name azfn-scg-dataprep \
  --resource-group BMG-OpenAI
```

**สาเหตุที่พบบ่อย**:
- Environment variables ไม่ครบ
- Container Registry credentials ไม่ถูกต้อง
- Image ขนาดใหญ่เกินไป (timeout ตอน pull)

### 3. ACR Authentication Failed

```bash
# ใช้ Admin credentials
az acr update --name bmgcontainer --admin-enabled true

# Get credentials
az acr credential show --name bmgcontainer
```

จากนั้นตั้งค่าใน Function App → Configuration:
```
DOCKER_REGISTRY_SERVER_URL=bmgcontainer.azurecr.io
DOCKER_REGISTRY_SERVER_USERNAME=<username>
DOCKER_REGISTRY_SERVER_PASSWORD=<password>
```

### 4. LibreOffice conversion failed

**ตรวจสอบ**:
```bash
# SSH เข้า container (ถ้า enable SSH)
az webapp ssh --name azfn-scg-dataprep --resource-group BMG-OpenAI

# ทดสอบ LibreOffice
libreoffice --version
```

---

## 📊 ข้อมูลเพิ่มเติม

### Docker Image Size

- **Base image**: `mcr.microsoft.com/azure-functions/python:4-python3.11` (~500MB)
- **+ LibreOffice**: ~200MB
- **+ Python packages**: ~300MB
- **Total**: ~1GB

### Cold Start Time

- **Without Docker**: ~2-5 seconds
- **With Docker**: ~10-20 seconds (ครั้งแรก)
- **Warm start**: ~1-2 seconds

### Cost Impact

Docker containers ใช้ resources มากกว่า:
- แนะนำใช้ **Premium Plan** (EP1 ขึ้นไป)
- หรือ **Dedicated Plan** (B1 ขึ้นไป)

---

## 🔄 อัปเดต Function Code

เมื่อแก้ไข `function_app.py` หรือไฟล์อื่นๆ:

```bash
# Build และ deploy image ใหม่
./docker-deploy.sh
```

Image จะถูก build ใหม่และ push ขึ้น registry อัตโนมัติ

---

## ✅ สรุป

| Feature | Zip Deployment | Docker Deployment |
|---------|----------------|-------------------|
| LibreOffice support | ❌ | ✅ |
| Deploy speed | Fast (~1 min) | Slower (~5-10 min) |
| Cold start | Fast (~2s) | Slower (~10-20s) |
| Cost | Lower | Higher |
| Flexibility | Limited | Full control |
| Recommended for | PDF-only | Office files support |

---

## 📚 References

- [Azure Functions Docker Containers](https://learn.microsoft.com/en-us/azure/azure-functions/functions-create-function-linux-custom-image)
- [Azure Container Registry](https://learn.microsoft.com/en-us/azure/container-registry/)
- [LibreOffice Headless](https://wiki.documentfoundation.org/Development/LibreOffice_Headless)
