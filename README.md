# Bits&Bytes Mail Server

A production-ready, resource-efficient mail server stack optimized for single VPS deployment on Ubuntu 24.04 LTS.

Features **Postfix** (SMTP), **Dovecot** (IMAP), **OpenDKIM** (DKIM signing), **Brevo** (Transactional HTTP relay), and a **Streamlit Admin Dashboard** for user lifecycle and quota management.

---

## Features

- 📧 **Full Email Stack**: Postfix + Dovecot + OpenDKIM for secure email receiving and IMAP access.
- 🚀 **Brevo Relay Integration**: Fast transactional email sending via Brevo HTTP REST API v3 fallback.
- 🎛️ **Single-File Streamlit Admin UI**: Manage mailboxes, passwords, alias mappings, forwards, quotas, and service health metrics.
- 🛠️ **Idempotent Reprovisioning CLI**: Automated VPS setup script (`cli/reprovision.sh`) with `--plan`, `--apply`, and `--verify` modes.
- 🔐 **Security First**: Environment configuration via `.env`, strict `.gitignore` safeguards, and UFW / Fail2ban firewall integration.

---

## Quickstart

### 1. Environment Setup

Copy `.env.example` to `.env` and fill in your deployment parameters:

```bash
cp .env.example .env
```

Key environment variables:
- `DOMAIN`: Your primary email domain (e.g. `example.com`)
- `MAIL_HOST`: Your mail server host (e.g. `mail.example.com`)
- `BREVO_API_KEY`: Brevo transactional API v3 key
- `AUDIT_BCC_EMAIL`: Audit / security notification address

### 2. Reprovision / Deploy on VPS

Run in dry-run mode to inspect the execution plan:

```bash
sudo ./cli/reprovision.sh --plan
```

Apply the provisioning steps on a fresh Ubuntu 24.04 VPS:

```bash
sudo ./cli/reprovision.sh --apply
```

Verify status of all mail services:

```bash
sudo ./cli/reprovision.sh --verify
```

### 3. Launch Admin Dashboard

```bash
/root/.env/bin/streamlit run mail-server-backend.py --server.address 127.0.0.1 --server.port 8501
```

---

## Architecture Overview

- `/etc/postfix/` - Postfix SMTP configuration, virtual maps, transport rules
- `/etc/dovecot/` - Dovecot IMAP configuration & authentication
- `/etc/opendkim/` - DKIM keys, SigningTable, KeyTable, TrustedHosts
- `scripts/brevo-send.py` - Transactional outbound mail engine via Brevo API v3
- `mail-server-backend.py` - Streamlit admin control panel
- `cli/reprovision.sh` - Stack reprovisioning CLI tool

For complete architectural details, see [tech-spec.md](tech-spec.md) and team directives in [AGENTS.md](AGENTS.md).

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.  
Copyright (c) 2026 **GOBITSNBYTES FOUNDATION**. All rights reserved.
