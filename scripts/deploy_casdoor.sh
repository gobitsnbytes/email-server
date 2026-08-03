#!/bin/bash

# Casdoor Deployment Script for gobitsnbytes.org VPS (Updated)
# Based on KT for v3.54.2, native binary, SQLite3, no Docker
# Run as root or with sudo. Manual steps (DNS, Certbot) are noted but not automated.

set -e  # Exit on any error

echo "Starting Casdoor v3.54.2 deployment on gobitsnbytes.org VPS..."

# Variables (adjusted for direct extraction to /opt)
CASDOOR_VERSION="v3.54.2"
BINARY_NAME="casdoor_Linux_x86_64.tar.gz"
DOWNLOAD_URL="https://github.com/casdoor/casdoor/releases/download/${CASDOOR_VERSION}/${BINARY_NAME}"
INSTALL_DIR="/opt"
CASDOOR_BINARY="${INSTALL_DIR}/casdoor"
CONFIG_FILE="${INSTALL_DIR}/conf/app.conf"
SERVICE_FILE="/etc/systemd/system/casdoor.service"
NGINX_SITE="/etc/nginx/sites-available/casdoor"
NGINX_ENABLED="/etc/nginx/sites-enabled/casdoor"

# Ensure we're working in /opt
cd "${INSTALL_DIR}"

# Step 2: Download and extract binary (extracts directly to /opt)
echo "Step 2: Downloading and extracting Casdoor binary..."
if [ ! -f "${BINARY_NAME}" ]; then
    wget "${DOWNLOAD_URL}"
else
    echo "Binary already exists, skipping download."
fi
if [ ! -f "${CASDOOR_BINARY}" ]; then
    tar -xzf "${BINARY_NAME}"
    echo "Extraction complete."
else
    echo "Casdoor binary already exists, skipping extraction."
fi

# Step 3: Configure SQLite3 (edit /opt/conf/app.conf)
echo "Step 3: Configuring SQLite3 in ${CONFIG_FILE}..."
if [ ! -f "${CONFIG_FILE}" ]; then
    echo "Config file not found! Check extraction."
    exit 1
fi
# Backup original config
cp "${CONFIG_FILE}" "${CONFIG_FILE}.backup"
# Write the exact config from KT
cat > "${CONFIG_FILE}" << 'EOF'
appname = casdoor
httpport = 8000
runmode = prod
SessionOn = true
copyrequestbody = true
driverName = sqlite
dataSourceName = file:casdoor.db?cache=shared
dbName = casdoor
tableNamePrefix =
showSql = false
redisEndpoint =
defaultStorageProvider =
isCloudIntranet = false
authState = "casdoor"
socks5Proxy =
verifyPeerCert = false
logConfig = {"filename": "/var/log/casdoor.log", "maxdays":99999, "perm":"0770"}
EOF
echo "Config updated. Original backed up to ${CONFIG_FILE}.backup"

# Step 4: Systemd service (adjusted paths)
echo "Step 4: Setting up systemd service..."
cat > "${SERVICE_FILE}" << EOF
[Unit]
Description=Casdoor IAM ${CASDOOR_VERSION}
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${CASDOOR_BINARY} --config ${CONFIG_FILE}
Restart=on-failure
RestartSec=5s
LimitNOFILE=65536
Environment=GOGC=50

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable casdoor
systemctl start casdoor

for i in {1..10}; do
  if curl -s http://127.0.0.1:8000 >/dev/null; then
    echo "Casdoor is responding on port 8000."
    break
  fi
  echo "Waiting for Casdoor to start..."
  sleep 1
done

echo "Service started. Checking status..."
systemctl status casdoor --no-pager
# Sanity check
if curl -s http://127.0.0.1:8000 > /dev/null; then
    echo "Casdoor is responding on port 8000."
else
    echo "Error: Casdoor not responding. Check logs with 'journalctl -u casdoor' or '${INSTALL_DIR}/casdoor.log'."
    exit 1
fi

# Step 5: Nginx config
echo "Step 5: Setting up Nginx..."
cat > "${NGINX_SITE}" << 'EOF'
server {
    listen 80;
    server_name auth.gobitsnbytes.org;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
if [ ! -L "${NGINX_ENABLED}" ]; then
    ln -s "${NGINX_SITE}" "${NGINX_ENABLED}"
fi
nginx -t
systemctl reload nginx
echo "Nginx reloaded."

# Step 7: Memory check
echo "Step 7: Memory and service status check..."
free -m
systemctl status casdoor postfix dovecot nginx --no-pager

echo ""
echo "Automated deployment complete!"
echo "Manual steps remaining:"
echo "- DNS: Add A record for 'auth.gobitsnbytes.org' pointing to your VPS IP."
echo "- TLS: Run 'certbot --nginx -d auth.gobitsnbytes.org' after DNS propagates."
echo "- First login: Visit https://auth.gobitsnbytes.org, login with admin/123, change password, and set up SAML/OIDC."
echo ""
echo "If issues arise, check logs: 'journalctl -u casdoor' or '/var/log/casdoor.log'."
