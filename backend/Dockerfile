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
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app
ENV SOFFICE_PATH=/usr/bin/soffice
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
