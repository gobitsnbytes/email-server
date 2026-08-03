# Mail Server Reproduction Guide

> Target audience: AI agents. This document contains the minimal instruction set to reproduce the Bits&Bytes mail server from scratch on a fresh Ubuntu 24.04 VPS.

## Prerequisites

- Fresh Ubuntu 24.04 VPS with root SSH access
- DNS control for `gobitsnbytes.org`
- Domain: `gobitsnbytes.org`
- Mail hostname: `mail.gobitsnbytes.org`
- VPS public IP: `<VPS_IP>`
- Brevo account with transactional SMTP API key

## File Inventory

All config files are in `configs/` with the same paths as the live server. The CLI `cli/reprovision.sh` applies them. Scripts are in `scripts/`.

### configs/
```
configs/postfix/main.cf
configs/postfix/master.cf
configs/postfix/virtual
configs/postfix/transport
configs/postfix/sender_bcc
configs/postfix/sasl_passwd
configs/dovecot/dovecot.conf
configs/dovecot/conf.d/10-auth.conf
configs/dovecot/conf.d/10-ssl.conf
configs/dovecot/conf.d/10-mail.conf
configs/dovecot/conf.d/10-master.conf
configs/dovecot/conf.d/90-quota.conf
configs/opendkim/KeyTable
configs/opendkim/SigningTable
configs/opendkim/TrustedHosts
configs/opendkim/keys/gobitsnbytes.org/default.private
configs/opendkim/keys/gobitsnbytes.org/mail.private
configs/nginx/sites-available/mail-admin.conf
configs/nginx/sites-available/casdoor.conf
configs/nginx/.mailadmin.htpasswd
configs/fail2ban/jail.local
configs/systemd/mail-admin.service
configs/systemd/casdoor.service
configs/ufw/applications
```

### scripts/
```
scripts/brevo-send.py
scripts/mail-admin-diag.sh
scripts/deploy_casdoor.sh
```

### Root files
```
mail-server-backend.py
mail-quota-policy.json
mail-admin-mode.json
```

## DNS Records Required

```dns
A       mail.gobitsnbytes.org.    <VPS_IP>
A       auth.gobitsnbytes.org.    <VPS_IP>
A       cal.gobitsnbytes.org.     <VPS_IP>
MX      gobitsnbytes.org.         10 mail.gobitsnbytes.org.
TXT     gobitsnbytes.org.         "v=spf1 a mx ip4:<VPS_IP> include:spf.brevo.com ~all"
TXT     default._domainkey        "v=DKIM1; h=sha256; k=rsa; p=<public_key>"
TXT     mail._domainkey           "v=DKIM1; h=sha256; k=rsa; p=<public_key>"
TXT     _dmarc                    "v=DMARC1; p=quarantine"
```

## Reproduction Steps (High-Level)

1. `cli/reprovision.sh --apply` (must be run as root on fresh VPS)
2. Obtain TLS certs: `certbot --nginx -d mail.gobitsnbytes.org -d auth.gobitsnbytes.org -d cal.gobitsnbytes.org`
3. Verify services: See `scripts/mail-admin-diag.sh`
4. Set Brevo API key in `/usr/local/bin/brevo-send.py`
5. Create mailbox users: Use streamlit admin at `https://mail.gobitsnbytes.org/admin/`
6. Onboard users with credential emails via Brevo

## Key Design Decisions

- **No Dovecot SQL/LDAP**: Uses PAM + system users. Simple, portable, no DB dependencies. `passdb { driver = pam }`, `userdb { driver = passwd }`.
- **Brevo relay**: All outbound mail goes through Brevo API via pipe(8) transport. Postfix never delivers directly to external MTAs. Eliminates deliverability/reputation management.
- **Transport map**: Explicitly routes major providers through brevo transport; `default_transport=brevo` catches everything else. Local delivery for `mail.gobitsnbytes.org`.
- **No real Dovecot quota enforcement**: Quota policy is stored in JSON file and displayed in UI, but dovecot is configured with static 1G quota. The `ENABLE_DOVECOT_USERDB_QUOTA_WRITES=False`.
- **Safe mode**: Streamlit UI has safe_mode toggle (persisted to `/root/mail-admin-mode.json`). When ON, all mutating operations are simulated.
- **DKIM**: Two selectors (default + mail) both signing. SigningTable wildcards all `@gobitsnbytes.org`.
- **Sender BCC**: Copies of all mail from `hello@` and `sponsors@` BCC'd to `gobitsnbytes@gmail.com` for audit.
- **Password management**: Passwords are auto-generated (18 chars, `secrets.choice`), set via `chpasswd`, shown once in UI, sent via Brevo email. Stored in system shadow (PAM).

## Maintenance

- **Cert renewal**: Certbot auto-renewal (systemd timer). Certs expire every 90 days.
- **Logs**: `/var/log/mail.log` (postfix+dovecot), `/var/log/nginx/error.log`
- **Queue management**: `mailq`, `postqueue -f`, or streamlit admin Queue page
- **Backup**: Periodically save `/etc/postfix/virtual`, `/etc/letsencrypt/live/`, `/root/mail-quota-policy.json`
- **User management**: Use streamlit admin (Mailboxes page) or direct: `useradd -m -s /usr/sbin/nologin USERNAME`
