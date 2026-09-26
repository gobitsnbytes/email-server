# bitsnbytes-mail-server tech-spec

## INFRA

```
OS:       Ubuntu 24.04.4 LTS (Noble Numbat), kernel 6.8.0-124-generic
VPS:      DigitalOcean, IP 139.59.31.120/20 (eth0), region: blr1
DNS MX:   mail.gobitsnbytes.org (priority 10)
DNS SPF:  "v=spf1 a mx ip4:168.144.1.208 include:spf.brevo.com ~all"
DNS DKIM: default._domainkey.gobitsnbytes.org (rsa), mail._domainkey (rsa)
DNS TXT:  brevo-code, zoho-verification, google-site-verification
```

## STACK

| Component | Role | Version |
|-----------|------|---------|
| postfix | MTA (inbound + outbound via brevo pipe) | 3.8.6 |
| dovecot | MDA (IMAP/POP3), SASL auth for postfix | 2.3.21 |
| opendkim | DKIM signing + verification (milter) | - |
| nginx | TLS termination, reverse proxy for admin UI | - |
| streamlit | Web admin panel (mail-server-backend.py) | 1.56.0 |
| fail2ban | Bruteforce protection (postfix, dovecot, sshd) | - |
| casdoor | IAM/OIDC (auth.gobitsnbytes.org) | v3.54.2 (SQLite3) |
| cal.com | Booking engine via nginx proxy (:3100) | node |
| brevo-send.py | Outbound SMTP relay via Brevo API | self-contained python |

## STREAMLIT ADMIN

```
Port:   127.0.0.1:8501
URL:    https://mail.gobitsnbytes.org/admin/ (nginx proxy_pass + auth_basic)
Auth:   /etc/nginx/.mailadmin.htpasswd (nginx basic auth; never commit hashes)
Systemd: mail-admin.service → /root/.venv/bin/streamlit run /root/mail-server-backend.py --server.address 127.0.0.1 --server.port 8501
```

The streamlit app toggles safe_mode via `/root/mail-admin-mode.json`. Current: `safe_mode=false`.

## POSTFIX CONFIG

### main.cf key params

| Key | Value |
|-----|-------|
| myhostname | mail.gobitsnbytes.org |
| mydomain | gobitsnbytes.org |
| myorigin | $mydomain |
| mydestination | $myhostname, localhost.$mydomain, localhost, $mydomain |
| home_mailbox | Maildir/ |
| mailbox_size_limit | 0 (unlimited) |
| inet_interfaces | all |
| inet_protocols | all |
| smtpd_tls_cert_file | /etc/letsencrypt/live/mail.gobitsnbytes.org/fullchain.pem |
| smtpd_tls_key_file | /etc/letsencrypt/live/mail.gobitsnbytes.org/privkey.pem |
| smtpd_tls_security_level | encrypt |
| smtpd_sasl_auth_enable | yes |
| smtpd_sasl_type | dovecot |
| smtpd_sasl_path | private/auth |
| smtpd_sasl_security_options | noanonymous |
| virtual_alias_maps | hash:/etc/postfix/virtual |
| smtpd_milters | inet:localhost:12301 (opendkim) |
| default_transport | brevo |
| relay_transport | brevo |
| sender_bcc_maps | hash:/etc/postfix/sender_bcc |

### transport map (/etc/postfix/transport)

```
mail.gobitsnbytes.org local:        # loopback for internal
gmail.com brevo:                    # force major providers via brevo
yahoo.com brevo:
outlook.com brevo:
hotmail.com brevo:
... (12 domain entries)
```

`default_transport=brevo` catches everything else. The `brevo` transport is a pipe(8) to `/usr/local/bin/brevo-send.py`.

### master.cf key additions

```
submission inet n - y - - smtpd       (port 587, STARTTLS)
submissions inet n - y - - smtpd      (port 465, SMTPS)
brevo unix - n n - - pipe flags=Rq user=nobody argv=/usr/local/bin/brevo-send.py ${recipient}
```

Note: submission/submissions do NOT override SASL settings (commented out). SASL is set at main.cf level.

### virtual alias map (/etc/postfix/virtual)

Comprehensive mapping of all users@domain → system usernames:

```
USER        SYSTEM USER
hello       hello

# Mailing lists (comma-separated expansions)
founders    
execs 
contributors 
everyone    all users

# Catch-all
@gobitsnbytes.org  hello@gobitsnbytes.org

# Tags in virtual file
# TAG: volunteer   (marker used by streamlit UI for grouping)
```

### sender_bcc map

```
hello@gobitsnbytes.org     gobitsnbytes@gmail.com
sponsors@gobitsnbytes.org  gobitsnbytes@gmail.com
```

BCC copies of all outgoing mail from hello/sponsors to audit address.

### /etc/aliases

```
postmaster: root
default:    hello
```

## DOVECOT CONFIG

### dovecot.conf (doveconf -n output)

```
auth_mechanisms = plain login
auth_username_format = %Ln
disable_plaintext_auth = no
mail_location = maildir:~/Maildir
ssl = required
ssl_cert = </etc/letsencrypt/live/mail.gobitsnbytes.org/fullchain.pem
ssl_key = </etc/letsencrypt/live/mail.gobitsnbytes.org/privkey.pem
ssl_dh = </usr/share/dovecot/dh.pem
ssl_client_ca_dir = /etc/ssl/certs

namespace inbox {
  inbox = yes
  mailbox Drafts { special_use = \Drafts }
  mailbox Junk { special_use = \Junk }
  mailbox Sent { special_use = \Sent }
  mailbox Trash { special_use = \Trash }
}

passdb { driver = pam }
userdb { driver = passwd }

plugin {
  quota = maildir:User quota
  quota_rule = *:storage=1G
  fts = xapian
  fts_autoindex = yes
  fts_enforced = yes
  fts_xapian = partial=3 full=20
}

protocols = " imap lmtp"
```

### 10-auth.conf: `auth_mechanisms = plain login`, `disable_plaintext_auth = no`, includes `auth-system.conf.ext` (PAM)

### 10-master.conf key: 
```
unix_listener /var/spool/postfix/private/auth { mode=0660 user=postfix group=postfix }
```
Postfix SASL auth socket.

### 90-quota.conf:
```
plugin { quota = maildir:User quota; quota_rule = *:storage=1G }
```

Default 1G quota. Per-user overrides in `/root/mail-quota-policy.json` via streamlit but dovecot quota is NOT dynamically updated (ENABLE_DOVECOT_USERDB_QUOTA_WRITES=False).

## OPENDKIM

```
Socket: inet:12301@localhost
Mode: sv (signing + verifying)
Canonicalization: relaxed/relaxed
KeyTable: /etc/opendkim/KeyTable
SigningTable: refile:/etc/opendkim/SigningTable
ExternalIgnoreList: /etc/opendkim/TrustedHosts
InternalHosts: /etc/opendkim/TrustedHosts
```

TrustedHosts: 127.0.0.1, localhost, 168.144.1.208, gobitsnbytes.org, mail.gobitsnbytes.org

### DKIM keys (rsa sha256):

| Selector | Key File | DNS Record |
|----------|----------|------------|
| default | /etc/opendkim/keys/gobitsnbytes.org/default.private | default._domainkey TXT |
| mail | /etc/opendkim/keys/gobitsnbytes.org/mail.private | mail._domainkey TXT |

SigningTable: `*@gobitsnbytes.org default._domainkey.gobitsnbytes.org`

## BREVO RELAY

```
Script:  /usr/local/bin/brevo-send.py
API Key: Configured via BREVO_API_KEY environment variable (.env)
Transport: postfix pipe(8) → brevo unix → brevo-send.py ${recipient}
```

The script reads RFC822 message from stdin, extracts plaintext body (with html→text fallback), constructs Brevo API v3 payload, POSTs to `https://api.brevo.com/v3/smtp/email`. Sender name derived from From header, co-erced to @gobitsnbytes.org.

## CERTBOT TLS

```
Domains:  mail.gobitsnbytes.org, auth.gobitsnbytes.org, cal.gobitsnbytes.org
Issuer:   Let's Encrypt (acme-v02.api.letsencrypt.org)
Account:  /etc/letsencrypt/accounts/acme-v02.api.letsencrypt.org/directory/b1aaabfcfd0802176dcf7aa81f9b3e87/
Renewal:  /etc/letsencrypt/renewal/{mail,auth,cal}.gobitsnbytes.org.conf
DH Params: /etc/letsencrypt/ssl-dhparams.pem
```

Cert paths for mail:
- fullchain: `/etc/letsencrypt/live/mail.gobitsnbytes.org/fullchain.pem`
- privkey: `/etc/letsencrypt/live/mail.gobitsnbytes.org/privkey.pem`

## NGINX

### mail.gobitsnbytes.org (port 443 ssl http2)

| Location | Target | Auth |
|----------|--------|------|
| `/admin/` | `http://127.0.0.1:8501/` | basic auth (htpasswd) + websocket proxy |
| `/webhooks/calcom` | `http://127.0.0.1:3100` | none |
| `/` | 404 | - |

### auth.gobitsnbytes.org → `http://127.0.0.1:8000` (casdoor)
### cal.gobitsnbytes.org → `http://127.0.0.1:3100` (cal.com)

## FIREWALL (UFW)

```
22/tcp  (SSH)
25/tcp  (SMTP)
80/tcp  (HTTP - certbot)
143/tcp (IMAP)
443/tcp (HTTPS)
587/tcp (SMTP submission)
993/tcp (IMAPS)
```

## FAIL2BAN JAILS

```
[DEFAULT] bantime=1h, findtime=10m, maxretry=5
[postfix] enabled on smtp,submission — logpath /var/log/mail.log
[dovecot] enabled on pop3,imap,submission,pop3s,imaps — logpath /var/log/mail.log
[sshd]    enabled on ssh — logpath /var/log/auth.log
```

## CASDOOR IAM

```
Binary:  /opt/casdoor (v3.54.2, native go binary, SQLite3)
Config:  /opt/conf/app.conf (httpport=8000, driverName=sqlite)
Systemd: casdoor.service (After=network.target, WorkingDirectory=/opt)
URL:     https://auth.gobitsnbytes.org (nginx proxy to :8000)
```

## MAILBOX USERS (system unix accounts, all /usr/sbin/nologin)

```
akshat, yash, aadrika, srishti, devaansh, maryam, hello, sponsors,
jaagruti, aishwary, kavan, areeb, atharva, prakhar, adithya, vareesha,
aanjaneya, noida, kolkata, solan, beawar, jaipur, hirdyansh, shantanu,
yashfeen, vijay, swastika, dia, hyderabad, noreply, bangalore, drishti,
raghav, adityatiwari, brentan
```

Total: 35 system users, each with ~/Maildir/{cur,new,tmp,.Sent,.Drafts,.Trash}

## QUOTA POLICY (file: /root/mail-quota-policy.json)

Per-user quota overrides. Default if absent: 1024MB (set in streamlit DEFAULT_NEW_USER_QUOTA_MB). Notable: yashfeen=128M, swastika=512M, dia=512M, adityatiwari=256M. All others=1024M.

## MAIL ADMIN CONTRACT (archived in /root/mail-admin-contract/)

```
README.txt         — system info snapshot
backend-contract.md — API contract spec (proposed REST endpoints)
cert-dates.txt     — TLS cert validity
doveconf-n.txt     — dovecot config dump
main.cf            — postfix main.cf copy
master.cf          — postfix master.cf copy
mailq.txt          — empty queue snapshot
mail.log.tail      — log tail sample
opendkim.status    — "active"
postfix.status     — "active"
dovecot.status     — "active"
postconf-n.txt     — postconf -n dump
transport          — transport map copy
virtual            — virtual map copy
10-auth.conf       — dovecot auth config
10-ssl.conf        — dovecot ssl config
10-master.conf     — dovecot master config
90-quota.conf      — dovecot quota config
```

## DIAGNOSTIC TOOL

`/root/mail-admin-diag.sh` — comprehensive diagnostic script that captures:
- system info, disk, services status
- ports, nginx config test
- mail log tail, mailq
- cert dates, DNS checks (dig A, MX, TXT)
- brevo-send.py syntax check
- dovecot login log analysis
- optionally send test via `--send recipient@example.com`

## USAGE PATTERNS

### Outbound mail flow:
```
user MUA → STARTTLS :587 → postfix submission → SASL auth (dovecot PAM) →
postfix cleanup → opendkim milter (signs) → brevo pipe → brevo-send.py →
Brevo API → recipient MTA
```

### Inbound mail flow:
```
remote MTA → :25 → postfix smtpd → opendkim milter (verifies) →
virtual_alias lookup → local delivery → dovecot IMAP :993
```

### Forward/alias resolution:
```
virtual_alias_maps → /etc/postfix/virtual (catch-all → hello, lists expand, forwards resolve)
→ if local user → Maildir delivery
→ if external → default_transport=brevo → brevo-send.py
```

## SENSITIVE VALUES (must be redacted for public git)

| Secret | Location |
|--------|----------|
| Brevo API key | /usr/local/bin/brevo-send.py (hardcoded) |
| sasl_passwd (relay creds) | /etc/postfix/sasl_passwd (unused) |
| htpasswd hash | /etc/nginx/.mailadmin.htpasswd |
| DKIM private keys | /etc/opendkim/keys/gobitsnbytes.org/*.private |
| LE account key | /etc/letsencrypt/accounts/*/private_key.json |
| LE privkey | /etc/letsencrypt/live/*/privkey.pem |
| Casdoor app.conf | /opt/conf/app.conf |
| Casdoor SQLite DB | /opt/casdoor.db |
