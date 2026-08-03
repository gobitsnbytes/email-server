# email-server

running your own mail server on a small VPS is usually a mess of scattered configs, broken deliverability, and unmaintainable shell scripts. this repo is how we run ours on a single Ubuntu 24.04 box without paying monthly per-mailbox fees or losing sleep over port 25 blocks.

it combines Postfix for incoming SMTP, Dovecot for IMAP, OpenDKIM for signing, Brevo's HTTP API for outbound delivery when residential or cloud IPs get flagged, and a single-file Streamlit panel so you do not need to edit raw `/etc/` files every time someone needs a password reset.

## how it works

- inbound mail comes straight to Postfix and Dovecot.
- outbound mail routes through `scripts/brevo-send.py` over HTTPS to bypass outbound port 25 restrictions.
- admin tasks happen via `mail-server-backend.py`, a Streamlit dashboard that edits virtual maps, user accounts, and quota policies safely.
- provisioning is handled by `cli/reprovision.sh`, an idempotent bash script with a mandatory `--plan` dry-run step so you can see changes before they touch system config.

## setup

1. copy the environment template:

```bash
cp .env.example .env
```

2. set your domain and credentials in `.env`:

```env
DOMAIN=gobitsnbytes.org
MAIL_HOST=mail.gobitsnbytes.org
BREVO_API_KEY=your_key_here
AUDIT_BCC_EMAIL=audit@gobitsnbytes.org
```

3. test the provisioning plan on a fresh Ubuntu 24.04 VPS:

```bash
sudo ./cli/reprovision.sh --plan
```

4. apply configuration:

```bash
sudo ./cli/reprovision.sh --apply
```

5. verify listening ports and service health:

```bash
sudo ./cli/reprovision.sh --verify
```

6. run the admin panel locally or behind a reverse proxy:

```bash
/root/.venv/bin/streamlit run mail-server-backend.py --server.address 127.0.0.1 --server.port 8501
```

## layout

- `cli/reprovision.sh`: full system setup script with `--plan`, `--apply`, and `--verify` modes.
- `mail-server-backend.py`: Streamlit management panel for mailboxes, virtual aliases, forwards, and quotas.
- `scripts/brevo-send.py`: Python CLI tool reading RFC822 messages from stdin and posting to Brevo API v3.
- `configs/`: production configuration files for Postfix, Dovecot, OpenDKIM, Nginx, systemd, and Fail2ban.
- `tech-spec.md`: complete architectural spec and DNS setup guide.
- `AGENTS.md`: operational rules and team guidelines.

## license

MIT License. Copyright (c) 2026 GOBITSNBYTES FOUNDATION.
