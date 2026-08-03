# AGENTS.md

Welcome to the **Bits&Bytes Mail Server Infrastructure** repository. This document defines our engineering standards, team guidelines, architecture overview, and operational directives.

---

## 1. Core Engineering Directives

- **Package Manager:** Always use `pnpm` for any Node/JavaScript tooling, scripts, or dependencies. Do not use `npm` or `yarn`.
- **Performance First:** All scripts and backend code must optimize for low latency, low resource footprint (TTFB, INP, memory utilization), and execution speed on resource-constrained VPS environments.
- **Security & Privacy Always:** Never commit live API keys, private keys (`.key`, `.pem`, `.private`), htpasswd files, or server logs (`*.log`, `*.log.tail`) to Git. All environment-specific parameters must be configured via `.env`.
- **Responsiveness:** All web UI components (e.g., Streamlit admin dashboards) must be responsive across mobile, tablet, and desktop viewports.

---

## 2. Environment & Secrets Management

This repository uses `.env` for managing sensitive credentials and environment-specific settings.

### Required Setup
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Populate `.env` with your deployment values:
   - `DOMAIN`: Your primary mail domain (e.g. `example.com`)
   - `MAIL_HOST`: Primary mail server FQDN (e.g. `mail.example.com`)
   - `BREVO_API_KEY`: Transactional email API key from Brevo
   - `BREVO_SMTP_USER` / `BREVO_SMTP_PASS`: Brevo SMTP relay credentials
   - `AUDIT_BCC_EMAIL`: Security audit notification address

All Python and Shell scripts automatically load values from `.env` or system environment variables with safe defaults.

---

## 3. Architecture Overview

- **Postfix (`/etc/postfix`):** SMTP server for receiving and relaying email.
- **Dovecot (`/etc/dovecot`):** IMAP server managing user mailboxes and authentication.
- **OpenDKIM (`/etc/opendkim`):** DKIM signing service for email deliverability.
- **Brevo Relay (`scripts/brevo-send.py`):** Transactional outbound mail delivery engine via HTTP REST API v3.
- **Mail Admin Panel (`mail-server-backend.py`):** Single-file Streamlit web app for user lifecycle management, alias mappings, quota management, and service monitoring.
- **Reprovision CLI (`cli/reprovision.sh`):** Idempotent shell automation script for reproducing the complete stack on a fresh Ubuntu 24.04 LTS VPS.

---

## 4. Operational Best Practices & Workflow

### Dry-Run First
When running provisioning scripts, always execute in dry-run / plan mode first:
```bash
sudo ./cli/reprovision.sh --plan
```

### Applying Provisioning
```bash
sudo ./cli/reprovision.sh --apply
```

### Verification
```bash
sudo ./cli/reprovision.sh --verify
```

---

## 5. Team Profiles & Responsibilities

- **Mail Infrastructure & Security Lead:** Responsible for Postfix/Dovecot/DKIM configuration, TLS certificate renewal, UFW firewall rules, and secret auditing.
- **Backend Developer:** Responsible for `mail-server-backend.py`, Streamlit admin UI features, Brevo API integrations, and Python scripts.
- **DevOps Engineer:** Responsible for `cli/reprovision.sh` automation, systemd unit files, and VPS environment provisioning.
