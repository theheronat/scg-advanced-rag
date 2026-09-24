# Azure Functions Python with LibreOffice
# Build for AMD64 (Azure) by passing --platform linux/amd64 to docker build / az acr build.
# Not set on FROM: ACR Tasks' dependency scanner cannot parse "FROM --platform=...".
FROM mcr.microsoft.com/azure-functions/python:4-python3.11

# Install system dependencies including LibreOffice
RUN apt-get update && apt-get install -y \
    libreoffice \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    fonts-liberation \
    fonts-dejavu-core \
    ghostscript \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

# Copy requirements and install Python dependencies
COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt

# Copy function app
COPY . /home/site/wwwroot

# Set permissions
RUN chmod -R 755 /home/site/wwwroot
