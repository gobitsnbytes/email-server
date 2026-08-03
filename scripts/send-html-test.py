#!/usr/bin/env python3
"""Sends the bits&bytes™ branded HTML credentials email via Brevo."""
import os
import subprocess
import sys
import textwrap
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote_plus


def load_env_file():
    """Load environment variables from .env file if present."""
    env_paths = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(".env"),
        Path("/root/.env"),
    ]
    for p in env_paths:
        if p.exists() and p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'").strip('"')
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass
            break


load_env_file()

DOMAIN = os.environ.get("DOMAIN", "gobitsnbytes.org")
MAIL_HOST = os.environ.get("MAIL_HOST", f"mail.{DOMAIN}")
BREVO_SEND_SCRIPT = os.environ.get("BREVO_SEND_SCRIPT", "/usr/local/bin/brevo-send.py")
AUDIT_BCC_EMAIL = os.environ.get("AUDIT_BCC_EMAIL", "gobitsnbytes@gmail.com")


# Brand colors
BG     = "#97192c"   # burgundy
ORANGE = "#fc920d"
INK    = "#120f0a"   # neutral base
MID    = "#a09f9d"   # neutral 60
LIGHT  = "#f5f4f2"


def build_html(mailbox_email: str, password_text: str) -> str:
    h = MAIL_HOST

    _ai_prompt = (
        f"I just received a new email account and need help setting it up. "
        f"My email address is {mailbox_email}. "
        f"The incoming mail server is {h} on port 993 with SSL/TLS. "
        f"The outgoing SMTP server is {h} on port 587 with STARTTLS. "
        f"My username is my full email address. "
        f"Please walk me through setting this up step by step — I'm not sure which device I'll use yet."
    )
    ai_q = quote_plus(_ai_prompt)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Mailbox credentials for {mailbox_email}</title>
</head>
<body style="margin:0;padding:0;background:{LIGHT};font-family:Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:{LIGHT};padding:40px 16px;">
  <tr><td align="center">
    <table width="100%" style="max-width:580px;">

      <!-- HEADER -->
      <tr>
        <td style="background:{BG};padding:36px 40px;border-radius:12px 12px 0 0;text-align:center;">
          <!-- Logo embedded inline — viewBox cropped to cube bounds (44–158, 64–194) so it renders square without distortion -->
          <svg width="56" height="56" viewBox="30 52 144 150" xmlns="http://www.w3.org/2000/svg"
               style="display:block;margin:0 auto 16px;">
            <defs>
              <mask id="bnb-logo">
                <path fill="#fff" d="m101.27586,64.293104 56.89655,32.810343V161.5862L101.46552,194.01724 44.568964,161.5862l.189656-65.051718z"/>
                <path fill="#000" d="m49.025862,107.06034v51.58621l46.086207,25.69828v-20.29311l-7.681037-4.36207.189656,11L56.61207,154l-.094828-11.47414 31.103618,17.16379-.189656-10.14655L56.61207,133.0431v-12.51724l31.008618,16.87931-.189656,12.42241 7.586208,4.07759.09483-21.81034z"/>
                <path fill="#000" d="m104.78448,133.61207 45.61207-25.41379.47414,21.05172-8.06035,4.26724v-11.56897l-30.62931,16.87931v11.75863L143,133.23276l-.0948,10.05172-30.81896,16.78448c0,0,.18965,13.18104-.0948,13.18104s-.28449,0-.28449,0l30.9138-17.06897v-12.70689l7.68103-4.26725.18966,19.9138-45.61207,26.83621z"/>
                <path fill="#000" d="m136.38627,98.970564c6.97353-4.023193,6.97353-4.023193,6.97353-4.023193L101.38448,70.405889l-39.561405,23.200418,8.046390,4.425513L101.65269,80.195662z"/>
                <path fill="#000" d="m104.33482,95.617905 6.30301,2.145702-6.1689,2.950343-2.54802,5.76658-2.548026-5.76658-6.571215-2.950343 6.437109-2.548023 2.413912-5.498364z"/>
              </mask>
            </defs>
            <path fill="#fff" mask="url(#bnb-logo)" d="m101.27586,64.293104 56.89655,32.810343V161.5862L101.46552,194.01724 44.568964,161.5862l.189656-65.051718z"/>
          </svg>
          <div style="color:#ffffff;font-size:26px;font-weight:700;letter-spacing:-0.5px;line-height:1;">
            bits&amp;bytes&#8482;
          </div>
          <div style="color:#f4d9d1;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-top:8px;">
            Mail Server
          </div>
        </td>
      </tr>

      <!-- BODY -->
      <tr>
        <td style="background:#ffffff;padding:40px 40px 32px;">
          <h1 style="color:{INK};font-size:22px;font-weight:700;margin:0 0 8px;line-height:1.2;">
            Your mailbox is ready.
          </h1>
          <p style="color:{MID};font-size:14px;margin:0 0 32px;line-height:1.6;">
            Here are your login credentials. Keep them safe — don't share this email.
          </p>

          <!-- Credentials card -->
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border:2px solid {BG};border-radius:10px;margin-bottom:36px;overflow:hidden;">
            <tr>
              <td style="background:#fdf8f8;padding:20px 24px;border-bottom:1px solid #f0e6e6;">
                <div style="color:{MID};font-size:10px;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:5px;">
                  Email address
                </div>
                <div style="color:{INK};font-size:16px;font-weight:600;font-family:'Courier New',Courier,monospace;">
                  {mailbox_email}
                </div>
              </td>
            </tr>
            <tr>
              <td style="background:#fdf8f8;padding:20px 24px;">
                <div style="color:{MID};font-size:10px;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:8px;">
                  Password
                </div>
                <div style="display:inline-block;background:#fff;color:{INK};font-size:16px;font-weight:600;
                            font-family:'Courier New',Courier,monospace;padding:8px 16px;
                            border:1.5px solid {BG};border-radius:6px;letter-spacing:1px;">
                  {password_text}
                </div>
              </td>
            </tr>
          </table>

          <!-- Setup heading -->
          <p style="color:{MID};font-size:11px;text-transform:uppercase;letter-spacing:1.5px;
                    margin:0 0 16px;font-weight:600;border-bottom:1px solid #ede9e7;padding-bottom:12px;">
            Setting it up
          </p>

          <!-- Gmail -->
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
            <tr>
              <td style="padding:16px 18px;background:#fafaf9;border:1px solid #ede9e7;border-radius:8px;">
                <div style="color:{INK};font-size:13px;font-weight:700;margin-bottom:8px;">
                  &#128241;&nbsp; Gmail App
                </div>
                <div style="color:{MID};font-size:12.5px;line-height:1.85;">
                  Profile pic &rarr; Add Account &rarr; Other &rarr; Personal (IMAP) &rarr; Enter password<br/>
                  <span style="color:#c8c5c2;">Incoming:</span>&nbsp;
                  <span style="color:{BG};font-family:monospace;font-weight:600;">{h}</span>
                  &nbsp;&middot;&nbsp;port <b style="color:{INK};">993</b>&nbsp;&middot;&nbsp;SSL/TLS<br/>
                  <span style="color:#c8c5c2;">Outgoing:</span>&nbsp;
                  <span style="color:{BG};font-family:monospace;font-weight:600;">{h}</span>
                  &nbsp;&middot;&nbsp;port <b style="color:{INK};">587</b>&nbsp;&middot;&nbsp;STARTTLS
                </div>
              </td>
            </tr>
          </table>

          <!-- iPhone -->
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
            <tr>
              <td style="padding:16px 18px;background:#fafaf9;border:1px solid #ede9e7;border-radius:8px;">
                <div style="color:{INK};font-size:13px;font-weight:700;margin-bottom:8px;">
                  &#127822;&nbsp; iPhone
                </div>
                <div style="color:{MID};font-size:12.5px;line-height:1.85;">
                  Settings &rarr; Mail &rarr; Add Account &rarr; Other &rarr; Fill in email + password<br/>
                  <span style="color:#c8c5c2;">Incoming:</span>&nbsp;
                  <span style="color:{BG};font-family:monospace;font-weight:600;">{h}</span>
                  &nbsp;&middot;&nbsp;port <b style="color:{INK};">993</b>&nbsp;&middot;&nbsp;SSL on<br/>
                  <span style="color:#c8c5c2;">Outgoing:</span>&nbsp;
                  <span style="color:{BG};font-family:monospace;font-weight:600;">{h}</span>
                  &nbsp;&middot;&nbsp;port <b style="color:{INK};">587</b>&nbsp;&middot;&nbsp;STARTTLS
                </div>
              </td>
            </tr>
          </table>

          <!-- Desktop -->
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
            <tr>
              <td style="padding:16px 18px;background:#fafaf9;border:1px solid #ede9e7;border-radius:8px;">
                <div style="color:{INK};font-size:13px;font-weight:700;margin-bottom:8px;">
                  &#128187;&nbsp; Thunderbird / Desktop
                </div>
                <div style="color:{MID};font-size:12.5px;line-height:1.85;">
                  <span style="color:#c8c5c2;">IMAP:</span>&nbsp;
                  <span style="color:{BG};font-family:monospace;font-weight:600;">{h}</span>
                  &nbsp;&middot;&nbsp;993&nbsp;&middot;&nbsp;SSL/TLS<br/>
                  <span style="color:#c8c5c2;">SMTP:</span>&nbsp;
                  <span style="color:{BG};font-family:monospace;font-weight:600;">{h}</span>
                  &nbsp;&middot;&nbsp;587&nbsp;&middot;&nbsp;STARTTLS<br/>
                  <span style="color:#c8c5c2;">Username:</span>&nbsp;your full email address
                </div>
              </td>
            </tr>
          </table>

          <!-- AI ASSISTANT BUTTONS -->
          <p style="color:{MID};font-size:11px;text-transform:uppercase;letter-spacing:1.5px;
                    margin:0 0 14px;font-weight:600;border-bottom:1px solid #ede9e7;padding-bottom:12px;">
            Need help setting it up?
          </p>
          <p style="color:{MID};font-size:12.5px;margin:0 0 16px;line-height:1.6;">
            Tap a button below — your account details will be sent to the AI automatically
            so it can walk you through the steps on any device.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td align="center" style="padding-bottom:10px;">
                <a href="https://chat.openai.com/?q={ai_q}"
                   style="display:inline-block;background:#10a37f;color:#fff;text-decoration:none;
                          font-size:13px;font-weight:700;padding:11px 22px;border-radius:7px;
                          margin:4px;letter-spacing:0.2px;">
                  Ask ChatGPT
                </a>
                <a href="https://gemini.google.com/app?q={ai_q}"
                   style="display:inline-block;background:#4285f4;color:#fff;text-decoration:none;
                          font-size:13px;font-weight:700;padding:11px 22px;border-radius:7px;
                          margin:4px;letter-spacing:0.2px;">
                  Ask Gemini
                </a>
              </td>
            </tr>
            <tr>
              <td align="center">
                <a href="https://www.perplexity.ai/?q={ai_q}"
                   style="display:inline-block;background:#1fb8cd;color:#fff;text-decoration:none;
                          font-size:13px;font-weight:700;padding:11px 22px;border-radius:7px;
                          margin:4px;letter-spacing:0.2px;">
                  Ask Perplexity
                </a>
                <a href="https://claude.ai/new?q={ai_q}"
                   style="display:inline-block;background:#d4762c;color:#fff;text-decoration:none;
                          font-size:13px;font-weight:700;padding:11px 22px;border-radius:7px;
                          margin:4px;letter-spacing:0.2px;">
                  Ask Claude
                </a>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- ORANGE ACCENT RULE -->
      <tr>
        <td style="background:{ORANGE};height:4px;font-size:0;line-height:0;">&nbsp;</td>
      </tr>

      <!-- FOOTER -->
      <tr>
        <td style="background:#ffffff;padding:20px 40px 28px;border-radius:0 0 12px 12px;
                   border-top:1px solid #ede9e7;text-align:center;">
          <p style="color:{MID};font-size:11px;margin:0;line-height:1.9;">
            <b style="color:{INK};">bits&amp;bytes&#8482;</b> by GOBITSNBYTES FOUNDATION<br/>
            &copy; 2026 GOBITSNBYTES FOUNDATION. All rights reserved.&nbsp;&middot;&nbsp;
            <a href="https://gobitsnbytes.org" style="color:{BG};text-decoration:none;">gobitsnbytes.org</a>
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def main():
    to_email      = sys.argv[1] if len(sys.argv) > 1 else AUDIT_BCC_EMAIL
    mailbox_email = sys.argv[2] if len(sys.argv) > 2 else f"hello@{DOMAIN}"
    password_text = sys.argv[3] if len(sys.argv) > 3 else "CHANGE_ME_PASSWORD"

    msg = EmailMessage()
    msg["From"]    = f"bits&bytes\u2122 <hello@{DOMAIN}>"
    msg["To"]      = to_email
    msg["Subject"] = f"Mailbox credentials for {mailbox_email}"

    plain = textwrap.dedent(f"""
        Hello,

        Your mailbox is ready.

        Email:    {mailbox_email}
        Password: {password_text}

        — Setting it up —

        Gmail App:
          Incoming: {MAIL_HOST} | port 993 | SSL/TLS
          Outgoing: {MAIL_HOST} | port 587 | STARTTLS

        iPhone:
          Incoming: {MAIL_HOST} | port 993 | SSL on
          Outgoing: {MAIL_HOST} | port 587 | STARTTLS

        Thunderbird / Desktop:
          IMAP: {MAIL_HOST} | 993 | SSL/TLS
          SMTP: {MAIL_HOST} | 587 | STARTTLS
          Username: your full email address

        Need help? Ask an AI:
          ChatGPT   — https://chat.openai.com
          Gemini    — https://gemini.google.com
          Perplexity — https://perplexity.ai
          Claude    — https://claude.ai

        --
        bits&bytes™ by GOBITSNBYTES FOUNDATION
        © 2026 GOBITSNBYTES FOUNDATION. All rights reserved.
        gobitsnbytes.org
    """).strip()

    msg.set_content(plain)
    msg.add_alternative(build_html(mailbox_email, password_text), subtype="html")

    raw = msg.as_string()
    r = subprocess.run(
        [BREVO_SEND_SCRIPT, to_email],
        input=raw, capture_output=True, text=True, timeout=40
    )
    print(r.stdout or r.stderr)
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
