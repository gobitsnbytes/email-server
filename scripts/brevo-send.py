#!/usr/bin/env python3
import email as emaillib
import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env_file():
    """Load delivery credentials from a file readable by the Postfix pipe user."""
    env_paths = [
        Path(os.environ.get("BREVO_ENV_FILE", "/etc/bnb-mail.env")),
        Path(__file__).resolve().parent.parent / ".env",
        Path(".env"),
        Path("/root/.env"),
    ]
    for p in env_paths:
        try:
            if p.exists() and p.is_file():
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'").strip('"')
                        if k and k not in os.environ:
                            os.environ[k] = v
                return
        except (OSError, UnicodeError):
            # The pipe runs as an unprivileged user and must skip root-only files.
            continue


load_env_file()

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
DOMAIN = os.environ.get("DOMAIN", "gobitsnbytes.org")


def decode_part_bytes(part):
    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        if raw_payload is None:
            return ""
        if isinstance(raw_payload, str):
            return raw_payload
        return str(raw_payload)

    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        return payload.decode("utf-8", errors="replace")


def html_to_text(value):
    if not value:
        return ""
    text = re.sub(r"(?is)<\s*br\s*/?\s*>", "\n", value)
    text = re.sub(r"(?is)<\s*/\s*p\s*>", "\n", text)
    text = re.sub(r"(?is)<\s*/\s*div\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_bodies(msg):
    text_body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition", "").lower().startswith("attachment"):
                continue

            ctype = (part.get_content_type() or "").lower()
            content = decode_part_bytes(part).strip()

            if ctype == "text/plain" and not text_body:
                text_body = content
            elif ctype == "text/html" and not html_body:
                html_body = content
    else:
        ctype = (msg.get_content_type() or "").lower()
        content = decode_part_bytes(msg).strip()
        if ctype == "text/html":
            html_body = content
        else:
            text_body = content

    return text_body, html_body


def extract_attachments(msg):
    """Convert MIME attachments to Brevo's base64 attachment payload."""
    attachments = []
    for part in msg.walk():
        filename = part.get_filename()
        if not filename or part.get_content_disposition() != "attachment":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        # Do not let a supplied MIME filename escape its intended attachment name.
        name = Path(filename).name or "attachment"
        attachments.append(
            {"name": name, "content": base64.b64encode(payload).decode("ascii")}
        )
    return attachments


def header_addresses(msg, header_name):
    """Return de-duplicated email addresses from a RFC 5322 address header."""
    seen = set()
    result = []
    for _, address in emaillib.utils.getaddresses(msg.get_all(header_name, [])):
        address = address.strip().lower()
        if "@" in address and address not in seen:
            seen.add(address)
            result.append(address)
    return result


def parse_from_header(from_header):
    from_header = (from_header or "").strip()
    if "<" in from_header and ">" in from_header:
        from_name = from_header.split("<", 1)[0].strip().strip('"')
        from_email = from_header.split("<", 1)[1].split(">", 1)[0].strip()
    else:
        from_email = from_header or f"noreply@{DOMAIN}"
        from_name = from_email.split("@")[0].capitalize() if "@" in from_email else "NoReply"

    if "@" in from_email and not from_email.lower().endswith(f"@{DOMAIN}"):
        from_email = from_email.split("@", 1)[0] + f"@{DOMAIN}"

    if not from_name:
        from_name = from_email.split("@")[0].capitalize() if "@" in from_email else "NoReply"

    return from_name, from_email


def safe_str(v, fallback=""):
    if v is None:
        return fallback
    if isinstance(v, str):
        return v
    return str(v)


def fix_unicode_escapes(text):
    if not text:
        return ""
    # Convert literal unicode escape sequences like \u2019 or \\u2019 to actual characters
    text = re.sub(r"\\?u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    # Convert smart quotes/apostrophes to clean standard ASCII characters
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return text


def main():
    if not BREVO_API_KEY:
        print('ERR: {"code":"missing_api_key","message":"BREVO_API_KEY is not set in environment or .env file"}', file=sys.stderr)
        sys.exit(1)

    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except Exception:
        raw = sys.stdin.read()

    msg = emaillib.message_from_string(raw)

    to_addr = safe_str(sys.argv[1] if len(sys.argv) > 1 else msg.get("To", ""), "").strip()
    subject = fix_unicode_escapes(safe_str(msg.get("Subject", "(no subject)"), "(no subject)").strip() or "(no subject)")
    from_name, from_email = parse_from_header(msg.get("From", f"noreply@{DOMAIN}"))

    text_body, html_body = extract_bodies(msg)
    attachments = extract_attachments(msg)

    # HARD GUARANTEE: never let textContent be absent/None/blank
    safe_text = safe_str(text_body, "").strip()
    if not safe_text:
        safe_text = html_to_text(safe_str(html_body, ""))
    if not safe_text:
        safe_text = " "  # one-space fallback to satisfy strict validators

    safe_text = fix_unicode_escapes(safe_text)
    if html_body:
        html_body = fix_unicode_escapes(safe_str(html_body, ""))

    if not to_addr:
        print('ERR: {"code":"missing_parameter","message":"recipient email is missing"}', file=sys.stderr)
        sys.exit(1)

    payload_obj = {
        "sender": {"email": from_email, "name": from_name},
        "to": [{"email": to_addr}],
        "subject": subject,
        "textContent": safe_text
    }

    # Preserve explicit Cc recipients and always copy the organization visibly.
    cc_addresses = header_addresses(msg, "Cc")
    audit_address = "gobitsnbytes@gmail.com"
    if to_addr.strip().lower() != audit_address and audit_address not in cc_addresses:
        cc_addresses.append(audit_address)
    if cc_addresses:
        payload_obj["cc"] = [{"email": address} for address in cc_addresses]

    if html_body:
        payload_obj["htmlContent"] = html_body
    if attachments:
        payload_obj["attachment"] = attachments

    payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print("OK:", body)
            sys.exit(0)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        debug = {
            "to_len": len(to_addr),
            "subject_len": len(subject),
            "text_len": len(safe_text),
            "has_html": bool(html_body),
        }
        print("ERR:", err_body, "| debug=", json.dumps(debug), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
