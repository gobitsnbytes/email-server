#!/usr/bin/env bash
# Simple diagnostics for mail.gobitsnbytes.org
# Saves diagnostics to /root
#
# Usage:
#   sudo bash /root/mail-admin-diag.sh           # run diagnostics only
#   sudo bash /root/mail-admin-diag.sh --send you@example.com
#
# Be cautious: --send will prompt before actually sending.

set -u

OUTDIR="/root"
TS=$(date -u +"%Y%m%dT%H%M%SZ")
OUTFILE="${OUTDIR}/mail-admin-diag-${TS}.log"

echo "Mail admin diag started at $(date -u)" > "$OUTFILE"
echo "Host: $(hostname)   Uptime: $(uptime -p)" >> "$OUTFILE"
echo >> "$OUTFILE"

# Helper to run and label commands
run() {
  echo "### $1" | tee -a "$OUTFILE"
  shift
  { echo "\$ $*"; "$@" ; } >> "$OUTFILE" 2>&1 || echo "[exit:$?]" >> "$OUTFILE"
  echo >> "$OUTFILE"
}

# Basic system info
run "uname -a" uname -a
run "python version" python3 --version || true
run "disk usage" df -h /

# Services
run "systemctl status postfix" systemctl status postfix --no-pager || true
run "systemctl status dovecot" systemctl status dovecot --no-pager || true
run "systemctl status opendkim" systemctl status opendkim --no-pager || true
run "systemctl status nginx" systemctl status nginx --no-pager || true
run "systemctl status mail-admin (streamlit service)" systemctl status mail-admin --no-pager || true

# Ports listening (common mail/web ports)
run "listening sockets for ports 25,587,993,80,443,8501" ss -ltnp | egrep -i ':(25|587|993|80|443|465|110|143|8501)' || true

# Local web/backend checks
run "curl localhost:8501 (streamlit)" curl -I --max-time 5 http://127.0.0.1:8501 || true
run "curl mail.gobitsnbytes.org (https)" curl -Ik --max-time 8 https://mail.gobitsnbytes.org || true

# Nginx config/test + last error lines
run "nginx -t" nginx -t || true
run "nginx error log (last 120 lines)" tail -n 120 /var/log/nginx/error.log || true

# Mail logs + mailq
run "tail mail.log (last 200 lines)" tail -n 200 /var/log/mail.log || true
run "mailq (queue snapshot)" mailq || true

# Postfix queue details (postqueue -p)
run "postqueue -p" postqueue -p || true

# Check cert
if [ -f /etc/letsencrypt/live/mail.gobitsnbytes.org/fullchain.pem ]; then
  run "openssl cert dates" openssl x509 -in /etc/letsencrypt/live/mail.gobitsnbytes.org/fullchain.pem -noout -dates || true
else
  echo "### cert file not found: /etc/letsencrypt/live/mail.gobitsnbytes.org/fullchain.pem" | tee -a "$OUTFILE"
fi
echo >> "$OUTFILE"

# DNS checks
run "dig A mail.gobitsnbytes.org" dig +short A mail.gobitsnbytes.org || true
run "dig MX gobitsnbytes.org" dig +short MX gobitsnbytes.org || true
run "dig TXT gobitsnbytes.org" dig +short TXT gobitsnbytes.org || true

# Check brevo-send.py exists and syntax
if [ -x /usr/local/bin/brevo-send.py ] || [ -f /usr/local/bin/brevo-send.py ]; then
  run "brevo-send.py exists and perms" ls -l /usr/local/bin/brevo-send.py || true
  run "brevo-send.py syntax check" python3 -m py_compile /usr/local/bin/brevo-send.py || true
else
  echo "### brevo-send.py not found at /usr/local/bin/brevo-send.py" | tee -a "$OUTFILE"
fi

# Authentication test helpers presence
run "swaks version (if installed)" sh -c 'which swaks && swaks --version' || true
run "doveadm version (if installed)" sh -c 'which doveadm && doveadm --version' || true

# Dovecot/login parsing sample
run "recent dovecot login lines (last 200)" grep -i "dovecot: .*login" /var/log/mail.log | tail -n 200 || true

# Disk inodes (rare cause)
run "df -i /" df -i / || true

echo "Diagnostics saved to: $OUTFILE"
echo >> "$OUTFILE"

# Optionally attempt a test send
SEND_FLAG=0
RECIP=""
if [ "${1:-}" = "--send" ] || [ "${2:-}" = "--send" ]; then
  # find recipient arg
  for a in "$@"; do
    if [ "$a" != "--send" ]; then
      RECIP="$a"
    fi
  done
  if [ -z "$RECIP" ]; then
    echo "No recipient provided for --send. Usage: $0 --send recipient@example.com"
  else
    SEND_FLAG=1
  fi
fi

if [ "$SEND_FLAG" -eq 1 ]; then
  echo
  echo "*** SEND MODE requested ***"
  echo "This will attempt to send a test message via /usr/local/bin/brevo-send.py to: $RECIP"
  read -p "Proceed with sending? Type YES to confirm: " CONF
  if [ "$CONF" = "YES" ]; then
    if [ -x /usr/local/bin/brevo-send.py ] || [ -f /usr/local/bin/brevo-send.py ]; then
      echo "Sending test message to $RECIP..." | tee -a "$OUTFILE"
      cat > /root/diag_test_msg.eml <<'EML'
From: hello@gobitsnbytes.org
To: RECIP
Subject: mail-admin diag test
Date: __DATE__

This is a diagnostic test message from mail-admin-diag.
EML
      sed -i "s/RECIP/${RECIP}/" /root/diag_test_msg.eml
      sed -i "s/__DATE__/$(date -u -R)/" /root/diag_test_msg.eml

      # send and capture output
      /usr/local/bin/brevo-send.py < /root/diag_test_msg.eml >> "$OUTFILE" 2>&1 || echo "brevo-send failed (see log)" >> "$OUTFILE"
      echo "Sent (see $OUTFILE for brevo-send output)" | tee -a "$OUTFILE"
    else
      echo "brevo-send.py not found => cannot send test mail" | tee -a "$OUTFILE"
    fi
  else
    echo "Send cancelled by user." | tee -a "$OUTFILE"
  fi
fi

echo
echo "Done. Diagnostics written to: $OUTFILE"
echo "Tail the file with: sudo tail -n 200 $OUTFILE"
exit 0
