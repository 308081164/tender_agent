#!/usr/bin/env bash
# Aspose.Words for Python (.NET Core 3.1) requires OpenSSL 1.1 on Linux.
# Ubuntu 22.04+ ships OpenSSL 3 only; install libssl1.1 for CI/desktop verification.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "install-aspose-linux-deps: skipped (not Linux)"
  exit 0
fi

if ldconfig -p 2>/dev/null | grep -q 'libssl\.so\.1\.1'; then
  echo "libssl.so.1.1 already available"
else
  echo "Installing libssl1.1 for Aspose .NET runtime..."
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  deb="$tmp/libssl1.1.deb"
  urls=(
    "http://security.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb"
    "http://archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1l-1ubuntu1_amd64.deb"
    "http://archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.0g-2ubuntu4_amd64.deb"
  )
  downloaded=0
  for url in "${urls[@]}"; do
    if curl -fsSL -o "$deb" "$url"; then
      downloaded=1
      break
    fi
  done
  if [[ "$downloaded" -ne 1 ]]; then
    echo "ERROR: failed to download libssl1.1 package" >&2
    exit 1
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo dpkg -i "$deb" || sudo apt-get install -f -y
  else
    dpkg -i "$deb" || apt-get install -f -y
  fi
  ldconfig -p | grep 'libssl\.so\.1\.1' || {
    echo "ERROR: libssl.so.1.1 not found after install" >&2
    exit 1
  }
fi

# ICU and base packages for verification.
if command -v apt-get >/dev/null 2>&1; then
  if ! ldconfig -p 2>/dev/null | grep -q 'libicu'; then
    if command -v sudo >/dev/null 2>&1; then
      sudo apt-get update -qq
      sudo apt-get install -y -qq libicu74 libssl3 ca-certificates python3-venv || \
        sudo apt-get install -y -qq libicu70 libssl3 ca-certificates python3-venv
    else
      apt-get update -qq
      apt-get install -y -qq libicu74 libssl3 ca-certificates python3-venv || \
        apt-get install -y -qq libicu70 libssl3 ca-certificates python3-venv
    fi
  fi
fi

echo "Aspose Linux dependencies ready"
