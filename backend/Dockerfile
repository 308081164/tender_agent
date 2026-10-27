FROM python:3.11-slim

WORKDIR /app

# Use a faster Debian mirror (China) before installing LibreOffice + CJK fonts.
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g; s|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
      sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
    fi

# LibreOffice for high-fidelity DOCX→PDF preview (arm64/amd64 via Debian packages).
# Prefer lighter CJK fonts (wqy) over fonts-noto-cjk (~57MB) for faster image builds.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libicu76 \
    libssl3 \
    ca-certificates \
    libreoffice-writer \
    libreoffice-java-common \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fonts-liberation \
    fontconfig \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Aspose.Words (.NET) needs OpenSSL 1.1 on Linux; Debian slim ships OpenSSL 3 only.
RUN set -eux; \
    for url in \
      "http://security.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb" \
      "http://archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1l-1ubuntu1_amd64.deb"; do \
      if curl -fsSL -o /tmp/libssl1.1.deb "$url"; then break; fi; \
    done; \
    apt-get install -y --no-install-recommends /tmp/libssl1.1.deb; \
    rm -f /tmp/libssl1.1.deb; \
    ldconfig -p | grep -q 'libssl\.so\.1\.1'

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app
ENV SOFFICE_PATH=/usr/bin/soffice
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
