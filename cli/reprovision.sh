#!/usr/bin/env bash
#===============================================================================
# bitsnbytes-mail-server reprovision CLI
# Reproduces the entire mail server stack on a fresh Ubuntu 24.04 VPS.
#
# Usage:
#   ./reprovision.sh --plan          # Dry-run: show what would be done (default)
#   ./reprovision.sh --apply         # Execute provisioning
#   ./reprovision.sh --verify        # Check status of all services
#   ./reprovision.sh --help          # This message
#
# SAFETY: --plan is the default. --apply prompts for confirmation.
# Run as root. idempotent where possible.
#===============================================================================
set -euo pipefail
IFS=$'\n\t'

#=== CONSTANTS =================================================================
SCRIPT_SRC="${SCRIPT_DIR:-/root/mail-server-repro}/scripts"
CONFIG_DIR="${CONFIG_DIR:-/root/mail-server-repro/configs}"

# Detect SCRIPT_DIR when piped via stdin (BASH_SOURCE is empty)
if [[ -z "${BASH_SOURCE[0]:-}" ]]; then
  SCRIPT_DIR="${SCRIPT_DIR:-/root/mail-server-repro}"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd 2>/dev/null || echo '/root/mail-server-repro')"
fi
SCRIPT_SRC="${SCRIPT_DIR}/scripts"
CONFIG_DIR="${SCRIPT_DIR}/configs"

# Source .env if present
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -o allexport
  source "${SCRIPT_DIR}/.env"
  set +o allexport
elif [[ -f "/root/.env" ]]; then
  set -o allexport
  source "/root/.env"
  set +o allexport
fi

DOMAIN="${DOMAIN:-gobitsnbytes.org}"
MAIL_HOST="${MAIL_HOST:-mail.${DOMAIN}}"
VPS_IP="${VPS_IP:-}"  # Set via env or prompt

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_err()   { echo -e "${RED}[ERR]${NC}   $*"; }
log_step()  { echo; echo -e "${GREEN}==>${NC} $*"; }
log_dry()   { echo -e "${YELLOW}[DRY]${NC}  $*"; }

#=== MODE ======================================================================
MODE="plan"
VERIFY_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --apply) MODE="apply";;
    --plan)  MODE="plan";;
    --verify) VERIFY_ONLY=true;;
    --help)
      head -20 "$0" | grep -E "^#" | sed 's/^#//'
      exit 0;;
  esac
done

#=== GUARD =====================================================================
if [[ $EUID -ne 0 ]]; then
  log_err "Must run as root."
  exit 1
fi

if [[ "$MODE" == "apply" ]]; then
  echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${RED}║  THIS WILL MODIFY SYSTEM CONFIGURATION                      ║${NC}"
  echo -e "${RED}║  Run on a FRESH Ubuntu 24.04 VPS only.                     ║${NC}"
  echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
  read -r -p "Type 'PROVISION' to confirm: " confirm
  if [[ "$confirm" != "PROVISION" ]]; then
    log_warn "Aborted."
    exit 1
  fi
fi

#=== HELPERS ===================================================================
run_cmd() {
  local desc="$1"; shift
  if [[ "$MODE" == "plan" ]]; then
    log_dry "$desc"
    return 0
  fi
  log_info "$desc"
  "$@" 2>&1 | sed 's/^/  /' || {
    local ec=$?
    log_err "Command failed (exit=$ec): $*"
    return $ec
  }
}

file_copy() {
  local src="${1:-}" dst="${2:-}"
  local desc="${3:-$dst}"
  if [[ -z "$src" ]] || [[ -z "$dst" ]]; then
    log_warn "file_copy: insufficient args (src=$src dst=$dst)"
    return 1
  fi
  if [[ "$MODE" == "plan" ]]; then
    log_dry "Copy: $src → $dst"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  if [[ -f "$src" ]]; then
    cp "$src" "$dst" && log_ok "Placed: $desc" || log_err "Failed: $desc"
  else
    log_warn "Missing source: $src (skip $desc)"
  fi
}

file_write() {
  local dst="${1:-}" content="${2:-}" desc="${3:-}"
  [[ -z "$desc" ]] && desc="$dst"
  if [[ "$MODE" == "plan" ]]; then
    log_dry "Write: $desc"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  echo "$content" > "$dst" && log_ok "Written: $desc" || log_err "Failed: $desc"
}

prompt_secret() {
  local var="$1" prompt="$2" default="${3:-}"
  if [[ -n "$default" ]]; then
    read -r -p "$prompt [$default]: " val
    echo "${val:-$default}"
  else
    read -r -p "$prompt: " val
    echo "$val"
  fi
}

systemd_unit_exists() {
  systemctl list-unit-files "$1" &>/dev/null
}

#=== VERIFICATION ==============================================================
verify_services() {
  log_step "Verification: service status"
  local services=("postfix" "dovecot" "opendkim" "nginx" "fail2ban" "casdoor" "mail-admin")
  local all_ok=true
  for svc in "${services[@]}"; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
      log_ok "$svc is active"
    else
      if [[ "$svc" == "casdoor" ]] || [[ "$svc" == "mail-admin" ]]; then
        log_warn "$svc is not active (optional, may not be deployed)"
      else
        log_err "$svc is not active"
        all_ok=false
      fi
    fi
  done

  log_step "Verification: listening ports"
  for port in 25 143 465 587 993 80 443 8501 8000 3100; do
    if ss -tlnp | grep -q ":$port "; then
      log_ok "Port $port listening"
    else
      log_warn "Port $port not listening"
    fi
  done

  log_step "Verification: mail queue"
  if mailq 2>/dev/null | grep -q "Mail queue is empty"; then
    log_ok "Mail queue empty"
  else
    mailq 2>/dev/null | wc -l | xargs -I{} log_warn "Mail queue has {} lines"
  fi

  log_step "Verification: cert expiry"
  if [[ -f /etc/letsencrypt/live/mail.gobitsnbytes.org/fullchain.pem ]]; then
    openssl x509 -in /etc/letsencrypt/live/mail.gobitsnbytes.org/fullchain.pem -noout -enddate 2>/dev/null
  else
    log_warn "No Let's Encrypt cert found for mail.gobitsnbytes.org"
  fi

  if $all_ok; then
    log_ok "All core services healthy"
  else
    log_warn "Some services need attention"
  fi
}

#=== DNS CHECK =================================================================
check_dns() {
  log_step "DNS check"
  local mx_ip
  mx_ip=$(dig +short MX "$DOMAIN" 2>/dev/null | head -1 | awk '{print $2}' | xargs dig +short A 2>/dev/null)
  if [[ -n "$mx_ip" ]]; then
    log_ok "MX for $DOMAIN resolves to $mx_ip"
  else
    log_warn "MX record for $DOMAIN not found. Set MX to $MAIL_HOST"
  fi

  if dig +short TXT "$DOMAIN" 2>/dev/null | grep -q "v=spf1"; then
    log_ok "SPF record found"
  else
    log_warn "SPF record missing. Add: v=spf1 a mx ip4:<VPS_IP> include:spf.brevo.com ~all"
  fi

  if dig +short TXT "default._domainkey.$DOMAIN" 2>/dev/null | grep -q "v=DKIM1"; then
    log_ok "DKIM default._domainkey found"
  else
    log_warn "DKIM default._domainkey missing. Publish the TXT record from configs/opendkim/keys/"
  fi
}

#=== STEP DEFINITIONS ==========================================================
step_install_packages() {
  log_step "1/14 Install system packages"
  local pkgs=(
    postfix postfix-mysql
    dovecot-imapd dovecot-pop3d dovecot-lmtpd dovecot-sieve dovecot-managesieved
    opendkim opendkim-tools
    nginx certbot python3-certbot-nginx
    fail2ban ufw
    swaks
    python3 python3-pip python3-venv
    wget curl openssl ca-certificates
    mailutils
    sqlite3
    dnsutils
  )
  run_cmd "apt-get update" apt-get update -y
  run_cmd "install packages: ${pkgs[*]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkgs[@]}"
}

step_stop_services() {
  log_step "2/14 Stop conflicting services"
  for svc in postfix dovecot opendkim nginx; do
    run_cmd "stop $svc" systemctl stop "$svc" 2>/dev/null || true
  done
}

step_place_postfix() {
  log_step "3/14 Place Postfix configs"
  for f in main.cf master.cf virtual transport sender_bcc; do
    file_copy "${CONFIG_DIR}/postfix/${f}" "/etc/postfix/${f}"
  done
  run_cmd "postmap virtual" postmap /etc/postfix/virtual
  run_cmd "postmap transport" postmap /etc/postfix/transport || log_warn "transport.db map failed"
  run_cmd "postmap sender_bcc" postmap /etc/postfix/sender_bcc || log_warn "sender_bcc.db map failed"
  # aliases
  file_write "/etc/aliases" "postmaster: root\n"
  run_cmd "newaliases" newaliases
}

step_place_dovecot() {
  log_step "4/14 Place Dovecot configs"
  file_copy "${CONFIG_DIR}/dovecot/dovecot.conf" "/etc/dovecot/dovecot.conf"
  for f in 10-auth.conf 10-ssl.conf 10-mail.conf 10-master.conf 90-quota.conf; do
    file_copy "${CONFIG_DIR}/dovecot/conf.d/${f}" "/etc/dovecot/conf.d/${f}"
  done
  run_cmd "create dh.pem if missing" openssl dhparam -out /usr/share/dovecot/dh.pem 2048 2>/dev/null || true
}

step_place_opendkim() {
  log_step "5/14 Place OpenDKIM configs"
  file_copy "${CONFIG_DIR}/opendkim/KeyTable" "/etc/opendkim/KeyTable"
  file_copy "${CONFIG_DIR}/opendkim/SigningTable" "/etc/opendkim/SigningTable"
  file_copy "${CONFIG_DIR}/opendkim/TrustedHosts" "/etc/opendkim/TrustedHosts"
  mkdir -p /etc/opendkim/keys/gobitsnbytes.org
  file_copy "${CONFIG_DIR}/opendkim/keys/gobitsnbytes.org/default.private" "/etc/opendkim/keys/gobitsnbytes.org/default.private"
  file_copy "${CONFIG_DIR}/opendkim/keys/gobitsnbytes.org/mail.private" "/etc/opendkim/keys/gobitsnbytes.org/mail.private"
  run_cmd "set DKIM key perms" chmod 600 /etc/opendkim/keys/gobitsnbytes.org/*.private
  run_cmd "set DKIM key owner" chown -R opendkim:opendkim /etc/opendkim/keys
  # Ensure opendkim.conf
  file_write "/etc/opendkim.conf" "\
PidFile /var/run/opendkim/opendkim.pid
Mode sv
Syslog yes
SyslogSuccess yes
LogWhy yes
Canonicalization relaxed/relaxed
MinimumKeyBits 1024
Socket inet:12301@localhost
Umask 002
SendReports yes
SoftwareHeader no
UserID opendkim
KeyTable /etc/opendkim/KeyTable
SigningTable refile:/etc/opendkim/SigningTable
ExternalIgnoreList /etc/opendkim/TrustedHosts
InternalHosts /etc/opendkim/TrustedHosts
"
}

step_place_nginx() {
  log_step "6/14 Place Nginx configs"
  mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
  file_copy "${CONFIG_DIR}/nginx/sites-available/mail-admin.conf" "/etc/nginx/sites-available/mail-admin.conf"
  file_copy "${CONFIG_DIR}/nginx/.mailadmin.htpasswd" "/etc/nginx/.mailadmin.htpasswd" 2>/dev/null || true

  # Enable sites
  if [[ -f /etc/nginx/sites-available/mail-admin.conf ]]; then
    ln -sf /etc/nginx/sites-available/mail-admin.conf /etc/nginx/sites-enabled/mail-admin.conf
  fi

  run_cmd "nginx config test" nginx -t || log_warn "nginx config test failed (expected before certs)"
}

step_place_fail2ban() {
  log_step "7/14 Place Fail2ban config"
  file_write "/etc/fail2ban/jail.local" "\
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
ignoreip = 127.0.0.1/8

[sshd]
enabled = true
port = ssh
logpath = /var/log/auth.log

[postfix]
enabled = true
port = smtp,submission
logpath = /var/log/mail.log

[dovecot]
enabled = true
port = pop3,imap,submission,pop3s,imaps
logpath = /var/log/mail.log
"
}

step_ufw() {
  log_step "8/14 Configure UFW"
  run_cmd "ufw allow 22/tcp" ufw allow 22/tcp
  run_cmd "ufw allow 25/tcp" ufw allow 25/tcp
  run_cmd "ufw allow 80/tcp" ufw allow 80/tcp
  run_cmd "ufw allow 143/tcp" ufw allow 143/tcp
  run_cmd "ufw allow 443/tcp" ufw allow 443/tcp
  run_cmd "ufw allow 587/tcp" ufw allow 587/tcp
  run_cmd "ufw allow 993/tcp" ufw allow 993/tcp
  run_cmd "ufw --force enable" ufw --force enable
}

step_python_venv() {
  log_step "9/14 Setup Python venv + Streamlit"
  run_cmd "create venv at /root/.venv" python3 -m venv /root/.venv || true
  run_cmd "install streamlit deps" /root/.venv/bin/pip install streamlit pandas requests 2>/dev/null || log_warn "pip install failed - check internet"
  file_copy "${SCRIPT_DIR}/mail-server-backend.py" "/root/mail-server-backend.py" || \
    log_warn "mail-server-backend.py not in repo - copy manually"
  file_copy "${SCRIPT_DIR}/mail-quota-policy.json" "/root/mail-quota-policy.json" 2>/dev/null || true
  file_copy "${SCRIPT_DIR}/mail-admin-mode.json" "/root/mail-admin-mode.json" 2>/dev/null || true
}

step_brevo_script() {
  log_step "10/14 Install Brevo send script"
  file_copy "${SCRIPT_SRC}/brevo-send.py" "/usr/local/bin/brevo-send.py"
  run_cmd "make brevo-send.py executable" chmod +x /usr/local/bin/brevo-send.py

  local api_key="${BREVO_API_KEY:-}"
  if [[ -z "$api_key" ]]; then
    api_key=$(prompt_secret "BREVO_API_KEY" "Enter Brevo API key" "")
  fi
  if [[ -n "$api_key" ]] && [[ "$MODE" == "apply" ]]; then
    file_write "/root/.env" "BREVO_API_KEY=${api_key}\nDOMAIN=${DOMAIN}\nMAIL_HOST=${MAIL_HOST}\n" "Environment file /root/.env"
    chmod 600 /root/.env
  fi
}

step_systemd_services() {
  log_step "11/14 Install systemd service units"

  file_write "/etc/systemd/system/mail-admin.service" "\
[Unit]
Description=BitsnBytes Mail Admin Streamlit
After=network.target

[Service]
WorkingDirectory=/root
ExecStart=/root/.venv/bin/streamlit run /root/mail-server-backend.py --server.address 127.0.0.1 --server.port 8501
Restart=always
User=root

[Install]
WantedBy=multi-user.target
"
}

step_start_services() {
  log_step "12/14 Start services"
  local services=("opendkim" "postfix" "dovecot" "nginx" "fail2ban")
  for svc in "${services[@]}"; do
    run_cmd "start $svc" systemctl enable "$svc"
    run_cmd "enable $svc" systemctl start "$svc" || log_warn "$svc failed to start"
  done
  # mail-admin.service
  run_cmd "enable mail-admin" systemctl daemon-reload
  run_cmd "start mail-admin" systemctl enable mail-admin
  run_cmd "enable mail-admin start" systemctl start mail-admin || log_warn "mail-admin failed to start"
}

step_create_users() {
  log_step "13/14 Create mailbox users"
  # Static user list from virtual file
  local users=(
    akshat yash aadrika srishti devaansh maryam hello sponsors
    jaagruti aishwary kavan areeb atharva prakhar adithya vareesha aanjaneya
    noida kolkata solan beawar jaipur hirdyansh shantanu yashfeen vijay
    swastika dia hyderabad noreply bangalore drishti raghav adityatiwari brentan
  )
  local created=0
  for user in "${users[@]}"; do
    if id "$user" &>/dev/null; then
      log_info "User $user exists (skip)"
    else
      if [[ "$MODE" == "apply" ]]; then
        run_cmd "create user $user" useradd -m -s /usr/sbin/nologin "$user"
        run_cmd "create Maildir for $user" mkdir -p "/home/$user/Maildir/{cur,new,tmp,.Sent,.Drafts,.Trash}"
        run_cmd "chown Maildir $user" chown -R "$user:$user" "/home/$user/Maildir"
        created=$((created + 1))
      else
        log_dry "create user $user with Maildir"
      fi
    fi
  done
  if [[ "$MODE" == "apply" ]]; then
    log_ok "Created $created new users (total: ${#users[@]})"
  fi
}

step_casdoor() {
  log_step "14/14 Optional: Casdoor IAM"
  if [[ -f "${SCRIPT_SRC}/deploy_casdoor.sh" ]]; then
    log_info "Casdoor deploy script found at ${SCRIPT_SRC}/deploy_casdoor.sh"
    if [[ "$MODE" == "apply" ]]; then
      log_info "Run manually: bash ${SCRIPT_SRC}/deploy_casdoor.sh"
      log_info "Or set up casdoor separately. Skipping auto-deploy."
    fi
  else
    log_warn "No casdoor deploy script in repo"
  fi
}

#=== MAIN ======================================================================
main() {
  echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║  bitsnbytes-mail-server reprovision                        ║${NC}"
  echo -e "${CYAN}║  Mode: ${MODE}                                               ║${NC}"
  echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"

  if $VERIFY_ONLY; then
    verify_services
    check_dns
    exit 0
  fi

  if [[ "$MODE" == "plan" ]]; then
    echo -e "\n${YELLOW}Running in --plan (dry-run) mode. Nothing will be modified.${NC}"
    echo -e "Use --apply to execute.\n"
  fi

  step_install_packages
  step_stop_services
  step_place_postfix
  step_place_dovecot
  step_place_opendkim
  step_place_nginx
  step_place_fail2ban
  step_ufw
  step_python_venv
  step_brevo_script
  step_systemd_services
  step_start_services
  step_create_users
  step_casdoor

  log_step "Complete"
  if [[ "$MODE" == "plan" ]]; then
    echo ""
    log_warn "Dry-run complete. No changes made."
    echo -e "  ${CYAN}Next:${NC} $0 --apply"
    echo -e "  ${CYAN}Then:${NC} certbot --nginx -d mail.gobitsnbytes.org -d auth.gobitsnbytes.org -d cal.gobitsnbytes.org"
    echo -e "  ${CYAN}Then:${NC} $0 --verify"
  else
    log_ok "Provisioning complete."
    log_info "Post-provision steps:"
    echo "  1. Obtain TLS certs: certbot --nginx -d mail.gobitsnbytes.org -d auth.gobitsnbytes.org -d cal.gobitsnbytes.org"
    echo "  2. Verify: $0 --verify"
    echo "  3. Access admin UI: https://mail.gobitsnbytes.org/admin/"
    echo "  4. Create passwords for users: chpasswd (or use streamlit)"
    echo "  5. Onboard users via Brevo credential emails"
  fi
}

main "$@"
