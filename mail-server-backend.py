# -*- coding: utf-8 -*-
import datetime
import json
import os
import pwd
import re
import secrets
import shlex
import string
import subprocess
import textwrap
from email.message import EmailMessage
from pathlib import Path
from urllib import error, request
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

def load_env_file():
    """Load environment variables from .env file if present."""
    env_paths = [
        Path(__file__).resolve().parent / ".env",
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

# =========================
# Config
# =========================
DOMAIN = os.environ.get("DOMAIN", "gobitsnbytes.org")
MAIL_HOST = os.environ.get("MAIL_HOST", f"mail.{DOMAIN}")
BREVO_SEND_SCRIPT = os.environ.get("BREVO_SEND_SCRIPT", "/usr/local/bin/brevo-send.py")
POSTFIX_VIRTUAL_FILE = os.environ.get("POSTFIX_VIRTUAL_FILE", "/etc/postfix/virtual")
LE_CERT_FULLCHAIN = os.environ.get("LE_CERT_FULLCHAIN", f"/etc/letsencrypt/live/{MAIL_HOST}/fullchain.pem")
MAIL_LOG_FILE = os.environ.get("MAIL_LOG_FILE", "/var/log/mail.log")

DEFAULT_WIKI_URL = os.environ.get("DEFAULT_WIKI_URL", "https://app.notion.com/p/33949ed2fc33818ba073ffa2d815bf1a?v=33949ed2fc3380ccbfe2000c860aa29a&source=copy_link")
AUDIT_BCC_EMAIL = os.environ.get("AUDIT_BCC_EMAIL", f"gobitsnbytes@gmail.com")
USE_HELLO_AS_SENDER = os.environ.get("USE_HELLO_AS_SENDER", "True").lower() in ("true", "1", "yes")

TAG_PREFIX = "# TAG:"
DEFAULT_NEW_USER_QUOTA_MB = int(os.environ.get("DEFAULT_NEW_USER_QUOTA_MB", "512"))
QUOTA_POLICY_FILE = os.environ.get("QUOTA_POLICY_FILE", "/root/mail-quota-policy.json")

ENABLE_DOVECOT_USERDB_QUOTA_WRITES = os.environ.get("ENABLE_DOVECOT_USERDB_QUOTA_WRITES", "False").lower() in ("true", "1", "yes")
DOVECOT_USERDB_FILE = os.environ.get("DOVECOT_USERDB_FILE", "/etc/dovecot/users")

# SAFE MODE (persisted; toggle in sidebar)
SAFE_MODE_FILE = os.environ.get("SAFE_MODE_FILE", "/root/mail-admin-mode.json")
DEFAULT_SAFE_MODE = os.environ.get("SAFE_MODE", "True").lower() in ("true", "1", "yes")



# =========================
# Streamlit config
# =========================
st.set_page_config(page_title="Bits&Bytes Mail Admin", layout="wide")
st.title("Bits&Bytes Mail Admin")
st.caption("Single-file Streamlit admin panel for Postfix + Dovecot + OpenDKIM + Brevo")


# =========================
# Generic helpers
# =========================
def now_utc_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def read_safe_mode() -> bool:
    p = Path(SAFE_MODE_FILE)
    if not p.exists():
        return DEFAULT_SAFE_MODE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return bool(data.get("safe_mode", DEFAULT_SAFE_MODE))
    except Exception:
        return DEFAULT_SAFE_MODE


def write_safe_mode(value: bool) -> dict:
    try:
        payload = {"safe_mode": bool(value), "updated_at": now_utc_iso()}
        Path(SAFE_MODE_FILE).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"ok": True, "safe_mode": bool(value)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def is_safe_mode() -> bool:
    return read_safe_mode()


def run_cmd(cmd: list[str], input_text: str | None = None, timeout: int = 25) -> dict:
    started = now_utc_iso()
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": " ".join(shlex.quote(c) for c in cmd),
            "started_at": started,
            "finished_at": now_utc_iso(),
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "ok": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "cmd": " ".join(shlex.quote(c) for c in cmd),
            "started_at": started,
            "finished_at": now_utc_iso(),
            "returncode": 124,
            "stdout": (e.stdout or "").strip() if isinstance(e.stdout, str) else "",
            "stderr": (e.stderr or "Command timed out").strip()
            if isinstance(e.stderr, str)
            else "Command timed out",
            "ok": False,
        }
    except Exception as e:
        return {
            "cmd": " ".join(shlex.quote(c) for c in cmd),
            "started_at": started,
            "finished_at": now_utc_iso(),
            "returncode": 1,
            "stdout": "",
            "stderr": f"{type(e).__name__}: {e}",
            "ok": False,
        }


def blocked_mutation(action: str) -> dict:
    return {
        "ok": False,
        "blocked": True,
        "simulated": True,
        "action": action,
        "message": f"{action} simulated only (SAFE_MODE=ON). No real changes applied.",
        "steps": [],
    }


def validate_username(username: str) -> tuple[bool, str]:
    if not username:
        return False, "Username is required."
    if not re.fullmatch(r"[a-z0-9_-]+", username):
        return False, "Username must match [a-z0-9_-]+ (lowercase only)."
    return True, ""


def generate_password(length: int = 18) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def parse_emails(csv_text: str) -> list[str]:
    if not csv_text.strip():
        return []
    return [e.strip() for e in csv_text.split(",") if e.strip()]


def pretty_status_label(result: dict) -> str:
    if result.get("blocked"):
        return "Blocked ⚠️ (Safe Mode)"
    return "Sent ✅" if result.get("ok") else "Failed ❌"


def sender_email() -> str:
    return f"hello@{DOMAIN}" if USE_HELLO_AS_SENDER else f"admin@{DOMAIN}"


def user_exists(username: str) -> bool:
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def local_part(email: str) -> str:
    return email.split("@", 1)[0].strip().lower()


def maybe_int(x: str, default: int = 0) -> int:
    try:
        return int(str(x).strip())
    except Exception:
        return default


def is_domain_mailbox(addr: str) -> bool:
    return addr.lower().endswith(f"@{DOMAIN}")


def safe_file_backup(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": True, "backup": "", "message": "source missing; no backup made"}
    ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    bpath = f"{path}.bak.{ts}"
    try:
        Path(bpath).write_text(
            p.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8"
        )
        return {"ok": True, "backup": bpath}
    except Exception as e:
        return {"ok": False, "backup": "", "message": f"{type(e).__name__}: {e}"}


# =========================
# Health + services
# =========================
def get_service_status(name: str) -> str:
    r = run_cmd(["systemctl", "is-active", name], timeout=10)
    if r["ok"] and r["stdout"]:
        return r["stdout"]
    return f"unknown ({r['stderr'] or 'no output'})"


def get_queue_count() -> int:
    r = run_cmd(["mailq"], timeout=20)
    out = (r["stdout"] + "\n" + r["stderr"]).strip()

    if "Mail queue is empty" in out:
        return 0

    m = re.search(r"in\s+(\d+)\s+Requests", out, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))

    ids = re.findall(r"^[A-F0-9]{5,}\*?!?\s", out, flags=re.MULTILINE | re.IGNORECASE)
    return len(ids)


def get_cert_dates(cert_path: str = LE_CERT_FULLCHAIN) -> dict:
    p = Path(cert_path)
    if not p.exists():
        return {"error": f"Certificate file not found: {cert_path}"}

    r = run_cmd(["openssl", "x509", "-in", cert_path, "-noout", "-dates"], timeout=10)
    if not r["ok"]:
        return {"error": r["stderr"] or "openssl failed"}

    d = {}
    for line in r["stdout"].splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


# =========================
# /etc/postfix/virtual parsing + write
# =========================
def read_virtual_lines() -> list[str]:
    f = Path(POSTFIX_VIRTUAL_FILE)
    if not f.exists():
        return []
    return f.read_text(encoding="utf-8", errors="ignore").splitlines()


def write_virtual_lines(lines: list[str]) -> None:
    text = "\n".join(lines).rstrip() + "\n"
    Path(POSTFIX_VIRTUAL_FILE).write_text(text, encoding="utf-8")


def postmap_and_reload_postfix() -> list[dict]:
    steps = []
    steps.append(run_cmd(["postmap", POSTFIX_VIRTUAL_FILE]))
    steps.append(run_cmd(["systemctl", "reload", "postfix"]))
    return steps


def load_virtual_map() -> dict:
    m = {}
    for line in read_virtual_lines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) >= 2:
            m[parts[0].lower()] = parts[1].lower()
    return m


def ensure_virtual_mapping(email: str, username: str) -> dict:
    lines = read_virtual_lines()
    found = False

    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) >= 2 and parts[0].lower() == email.lower():
            lines[i] = f"{email} {username}"
            found = True
            break

    if not found:
        lines.append(f"{email} {username}")

    write_virtual_lines(lines)
    return {"ok": True, "updated": True, "found_existing": found}


def remove_virtual_mapping(email: str, username: str) -> dict:
    lines = read_virtual_lines()
    kept = []
    removed_count = 0

    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            kept.append(raw)
            continue
        parts = s.split()
        if (
            len(parts) >= 2
            and parts[0].lower() == email.lower()
            and parts[1].lower() == username.lower()
        ):
            removed_count += 1
            continue
        kept.append(raw)

    write_virtual_lines(kept)
    return {"ok": True, "removed": removed_count}


# =========================
# Mailing lists / forwards / tags
# =========================
def parse_virtual_struct() -> dict:
    lines = read_virtual_lines()
    lists_raw: dict[str, list[str]] = {}
    forwards: list[dict] = []
    mailbox_mappings: list[dict] = []
    catch_all: str | None = None
    tags: list[str] = []

    current_tag = ""

    for idx, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue

        if s.startswith("#"):
            if s.upper().startswith(TAG_PREFIX):
                t = s[len(TAG_PREFIX) :].strip()
                if t:
                    current_tag = t
                    if t not in tags:
                        tags.append(t)
            continue

        parts = s.split()
        if len(parts) < 2:
            continue

        src = parts[0].lower()
        dst = parts[1].lower()

        if src == f"@{DOMAIN}":
            catch_all = dst
            continue

        src_domain_ok = src.endswith(f"@{DOMAIN}")
        dst_domain_ok = dst.endswith(f"@{DOMAIN}")

        if src_domain_ok and dst_domain_ok:
            src_local = local_part(src)
            dst_local = local_part(dst)
            if src_local == dst_local:
                mailbox_mappings.append(
                    {
                        "line": idx + 1,
                        "source": src,
                        "target": dst_local,
                        "tag": current_tag,
                    }
                )
            else:
                lists_raw.setdefault(src, []).append(dst)
        elif src_domain_ok and (not dst_domain_ok):
            forwards.append(
                {"line": idx + 1, "source": src, "target": dst, "tag": current_tag}
            )

    list_rows = []
    for addr, members in lists_raw.items():
        list_rows.append(
            {
                "address": addr,
                "members": ", ".join(members),
                "member_count": len(members),
            }
        )

    return {
        "lists": sorted(list_rows, key=lambda x: x["address"]),
        "lists_raw": lists_raw,
        "forwards": sorted(forwards, key=lambda x: (x["source"], x["target"])),
        "mailbox_mappings": mailbox_mappings,
        "catch_all": catch_all,
        "tags": sorted(tags),
        "line_count": len(lines),
    }


def add_list_member(list_address: str, member_email: str, tag: str = "") -> dict:
    if is_safe_mode():
        return blocked_mutation("add_list_member")

    list_address = list_address.strip().lower()
    member_email = member_email.strip().lower()
    if not is_domain_mailbox(list_address):
        return {"ok": False, "message": f"List address must be @{DOMAIN}", "steps": []}
    if "@" not in member_email:
        return {"ok": False, "message": "Member email must be valid", "steps": []}

    lines = read_virtual_lines()
    wanted = f"{list_address} {member_email}"
    for raw in lines:
        if raw.strip().lower() == wanted:
            return {"ok": True, "message": "Member already present", "steps": []}

    if tag.strip():
        marker = f"{TAG_PREFIX} {tag.strip()}"
        if marker not in [x.strip() for x in lines]:
            lines.append(marker)

    lines.append(wanted)
    write_virtual_lines(lines)
    steps = postmap_and_reload_postfix()
    return {
        "ok": all(s["ok"] for s in steps),
        "steps": steps,
        "message": f"Added {member_email} to {list_address}",
    }


def remove_list_member(list_address: str, member_email: str) -> dict:
    if is_safe_mode():
        return blocked_mutation("remove_list_member")

    list_address = list_address.strip().lower()
    member_email = member_email.strip().lower()
    lines = read_virtual_lines()
    kept = []
    removed = 0

    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            kept.append(raw)
            continue
        parts = s.split()
        if (
            len(parts) >= 2
            and parts[0].lower() == list_address
            and parts[1].lower() == member_email
        ):
            removed += 1
            continue
        kept.append(raw)

    write_virtual_lines(kept)
    steps = postmap_and_reload_postfix()
    return {
        "ok": all(s["ok"] for s in steps),
        "steps": steps,
        "removed": removed,
        "message": f"Removed {removed} matching entries",
    }


def add_forward(source_email: str, target_email: str, tag: str = "") -> dict:
    if is_safe_mode():
        return blocked_mutation("add_forward")

    source_email = source_email.strip().lower()
    target_email = target_email.strip().lower()

    if not is_domain_mailbox(source_email):
        return {"ok": False, "message": f"Source must be @{DOMAIN}", "steps": []}
    if "@" not in target_email:
        return {"ok": False, "message": "Target must be an email", "steps": []}

    lines = read_virtual_lines()
    wanted = f"{source_email} {target_email}"
    for raw in lines:
        if raw.strip().lower() == wanted:
            return {"ok": True, "message": "Forward already present", "steps": []}

    if tag.strip():
        marker = f"{TAG_PREFIX} {tag.strip()}"
        if marker not in [x.strip() for x in lines]:
            lines.append(marker)

    lines.append(wanted)
    write_virtual_lines(lines)
    steps = postmap_and_reload_postfix()
    return {
        "ok": all(s["ok"] for s in steps),
        "steps": steps,
        "message": f"Added forward {source_email} -> {target_email}",
    }


def remove_forward(source_email: str, target_email: str) -> dict:
    if is_safe_mode():
        return blocked_mutation("remove_forward")

    source_email = source_email.strip().lower()
    target_email = target_email.strip().lower()
    lines = read_virtual_lines()
    kept = []
    removed = 0

    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            kept.append(raw)
            continue
        parts = s.split()
        if (
            len(parts) >= 2
            and parts[0].lower() == source_email
            and parts[1].lower() == target_email
        ):
            removed += 1
            continue
        kept.append(raw)

    write_virtual_lines(kept)
    steps = postmap_and_reload_postfix()
    return {"ok": all(s["ok"] for s in steps), "steps": steps, "removed": removed}


def add_tag(tag: str) -> dict:
    if is_safe_mode():
        return blocked_mutation("add_tag")

    t = tag.strip()
    if not t:
        return {"ok": False, "message": "Tag required", "steps": []}

    lines = read_virtual_lines()
    marker = f"{TAG_PREFIX} {t}"
    if marker in [x.strip() for x in lines]:
        return {"ok": True, "message": "Tag already exists", "steps": []}

    lines.append(marker)
    write_virtual_lines(lines)
    steps = postmap_and_reload_postfix()
    return {
        "ok": all(s["ok"] for s in steps),
        "steps": steps,
        "message": f"Tag '{t}' added",
    }


def remove_tag(tag: str) -> dict:
    if is_safe_mode():
        return blocked_mutation("remove_tag")

    t = tag.strip()
    marker = f"{TAG_PREFIX} {t}"

    lines = read_virtual_lines()
    kept = []
    removed = 0
    for raw in lines:
        if raw.strip() == marker:
            removed += 1
            continue
        kept.append(raw)

    write_virtual_lines(kept)
    steps = postmap_and_reload_postfix()
    return {"ok": all(s["ok"] for s in steps), "steps": steps, "removed": removed}


# =========================
# Mailboxes operations
# =========================
@st.cache_data(ttl=30)
def list_mailboxes() -> list[dict]:
    home_root = Path("/home")
    if not home_root.exists():
        return []

    virtual_map = load_virtual_map()
    rows = []

    for p in sorted(home_root.iterdir()):
        if not p.is_dir():
            continue

        user = p.name
        try:
            pw = pwd.getpwnam(user)
            uid = pw.pw_uid
            shell = pw.pw_shell
            home = pw.pw_dir
        except KeyError:
            uid = None
            shell = ""
            home = str(p)

        if uid is not None and uid < 1000 and user != "root":
            continue

        email = f"{user}@{DOMAIN}"
        rows.append(
            {
                "username": user,
                "email": email,
                "home": home,
                "shell": shell,
                "maildir_exists": "✅" if (p / "Maildir").exists() else "❌",
                "virtual_mapped": "✅" if email.lower() in virtual_map else "❌",
                "virtual_target": virtual_map.get(email.lower(), ""),
            }
        )

    return rows


def create_mailbox_autogen(
    username: str, quota_mb: int = DEFAULT_NEW_USER_QUOTA_MB
) -> dict:
    if is_safe_mode():
        return blocked_mutation("create_mailbox")

    valid, msg = validate_username(username)
    if not valid:
        return {"ok": False, "blocked": False, "message": msg, "steps": []}

    if user_exists(username):
        return {
            "ok": False,
            "blocked": False,
            "message": f"User '{username}' already exists.",
            "steps": [],
        }

    password = generate_password()
    steps = []

    b = safe_file_backup(POSTFIX_VIRTUAL_FILE)
    if not b.get("ok", False):
        return {
            "ok": False,
            "blocked": False,
            "message": f"Backup failed: {b.get('message', '')}",
            "steps": [],
        }
    steps.append(
        {
            "cmd": f"backup {POSTFIX_VIRTUAL_FILE}",
            "started_at": now_utc_iso(),
            "finished_at": now_utc_iso(),
            "returncode": 0,
            "stdout": b.get("backup", ""),
            "stderr": "",
            "ok": True,
        }
    )

    steps.append(run_cmd(["useradd", "-m", "-s", "/usr/sbin/nologin", username]))
    steps.append(run_cmd(["chpasswd"], input_text=f"{username}:{password}\n"))

    home = Path("/home") / username
    steps.append(run_cmd(["mkdir", "-p", str(home / "Maildir" / "cur")]))
    steps.append(run_cmd(["mkdir", "-p", str(home / "Maildir" / "new")]))
    steps.append(run_cmd(["mkdir", "-p", str(home / "Maildir" / "tmp")]))
    steps.append(run_cmd(["mkdir", "-p", str(home / "Maildir" / ".Sent")]))
    steps.append(run_cmd(["mkdir", "-p", str(home / "Maildir" / ".Drafts")]))
    steps.append(run_cmd(["mkdir", "-p", str(home / "Maildir" / ".Trash")]))
    steps.append(
        run_cmd(["chown", "-R", f"{username}:{username}", str(home / "Maildir")])
    )

    email = f"{username}@{DOMAIN}"
    try:
        ensure_virtual_mapping(email, username)
        steps.append(
            {
                "cmd": f"ensure mapping '{email} {username}'",
                "started_at": now_utc_iso(),
                "finished_at": now_utc_iso(),
                "returncode": 0,
                "stdout": "mapping ensured",
                "stderr": "",
                "ok": True,
            }
        )
    except Exception as e:
        steps.append(
            {
                "cmd": f"ensure mapping '{email} {username}'",
                "started_at": now_utc_iso(),
                "finished_at": now_utc_iso(),
                "returncode": 1,
                "stdout": "",
                "stderr": f"{type(e).__name__}: {e}",
                "ok": False,
            }
        )

    steps.extend(postmap_and_reload_postfix())

    quota_res = set_quota_policy(username, quota_mb)
    ok = all(s["ok"] for s in steps) and quota_res["ok"]

    return {
        "ok": ok,
        "blocked": False,
        "steps": steps + quota_res.get("steps", []),
        "email": email,
        "username": username,
        "generated_password": password if ok else "",
        "quota_mb": quota_mb,
        "message": "Mailbox created." if ok else "Mailbox creation failed.",
    }


def reset_password_autogen(username: str) -> dict:
    if is_safe_mode():
        return blocked_mutation("reset_password")

    if not user_exists(username):
        return {
            "ok": False,
            "blocked": False,
            "message": f"User '{username}' not found.",
            "steps": [],
        }

    new_password = generate_password()
    step = run_cmd(["chpasswd"], input_text=f"{username}:{new_password}\n")

    return {
        "ok": step["ok"],
        "blocked": False,
        "steps": [step],
        "username": username,
        "new_password": new_password if step["ok"] else "",
        "message": "Password reset done." if step["ok"] else "Password reset failed.",
    }


def delete_mailbox(username: str) -> dict:
    if is_safe_mode():
        return blocked_mutation("delete_mailbox")

    if not user_exists(username):
        return {
            "ok": False,
            "blocked": False,
            "message": f"User '{username}' not found.",
            "steps": [],
        }

    steps = []
    email = f"{username}@{DOMAIN}"

    b = safe_file_backup(POSTFIX_VIRTUAL_FILE)
    if not b.get("ok", False):
        return {
            "ok": False,
            "blocked": False,
            "message": f"Backup failed: {b.get('message', '')}",
            "steps": [],
        }
    steps.append(
        {
            "cmd": f"backup {POSTFIX_VIRTUAL_FILE}",
            "started_at": now_utc_iso(),
            "finished_at": now_utc_iso(),
            "returncode": 0,
            "stdout": b.get("backup", ""),
            "stderr": "",
            "ok": True,
        }
    )

    try:
        rm = remove_virtual_mapping(email, username)
        steps.append(
            {
                "cmd": f"remove mapping '{email} {username}'",
                "started_at": now_utc_iso(),
                "finished_at": now_utc_iso(),
                "returncode": 0,
                "stdout": f"removed={rm.get('removed', 0)}",
                "stderr": "",
                "ok": True,
            }
        )
    except Exception as e:
        steps.append(
            {
                "cmd": f"remove mapping '{email} {username}'",
                "started_at": now_utc_iso(),
                "finished_at": now_utc_iso(),
                "returncode": 1,
                "stdout": "",
                "stderr": f"{type(e).__name__}: {e}",
                "ok": False,
            }
        )

    steps.extend(postmap_and_reload_postfix())
    steps.append(run_cmd(["userdel", "-r", username]))

    qp = read_quota_policy()
    if username in qp:
        del qp[username]
        write_quota_policy(qp)

    ok = all(s["ok"] for s in steps)
    return {
        "ok": ok,
        "blocked": False,
        "steps": steps,
        "username": username,
        "message": "Mailbox deleted." if ok else "Mailbox delete failed.",
    }


# =========================
# Credential email / Brevo pipe
# =========================
def build_credentials_html(mailbox_email: str, password_text: str) -> str:
    # Logo served from official brand asset URL per brand guidelines
    BG     = "#97192c"
    ORANGE = "#fc920d"
    INK    = "#120f0a"
    MID    = "#a09f9d"
    LIGHT  = "#f5f4f2"
    h      = MAIL_HOST

    # Pre-encode the setup prompt so AI buttons work with zero JS in email clients
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
          <!-- Logo embedded inline — viewBox cropped to cube bounds so it renders square without distortion -->
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
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
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
            Tap one of the buttons below — your setup details will be sent automatically
            to the AI so it can walk you through the steps on any device.
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


def build_credentials_message(
    to_email: str, mailbox_email: str, password_text: str, wiki_url: str
) -> str:
    msg = EmailMessage()
    msg["From"] = sender_email()
    msg["To"] = to_email
    msg["Bcc"] = AUDIT_BCC_EMAIL
    msg["Subject"] = f"Mailbox credentials for {mailbox_email}"

    plain = textwrap.dedent(
        f"""
        Hello,

        Your mailbox is ready.

        Email: {mailbox_email}
        Password: {password_text}

        -- setting it up --

        Gmail app:
        profile pic -> add account -> other -> enter your email -> personal (IMAP) -> enter password
        incoming: {MAIL_HOST} | port 993 | SSL/TLS
        outgoing: {MAIL_HOST} | port 587 | STARTTLS

        iPhone:
        settings -> mail -> add account -> other -> fill in email + password
        incoming: {MAIL_HOST} | port 993 | SSL on
        outgoing: {MAIL_HOST} | port 587 | STARTTLS (recommended)

        Thunderbird/Desktop:
        IMAP: {MAIL_HOST} | 993 | SSL/TLS
        SMTP: {MAIL_HOST} | 587 | STARTTLS
        username: your full email address

        Webmail: https://{MAIL_HOST}

        --
        Bits&Bytes Mail Server
        """
    ).strip()

    msg.set_content(plain)
    msg.add_alternative(build_credentials_html(mailbox_email, password_text), subtype="html")
    return msg.as_string()


def send_via_brevo(raw_message: str) -> dict:
    if is_safe_mode() and not ALLOW_BREVO_SEND_IN_DRY_RUN:
        return {
            "ok": False,
            "blocked": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "Blocked by SAFE_MODE policy.",
        }

    if not Path(BREVO_SEND_SCRIPT).exists():
        return {
            "ok": False,
            "blocked": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "brevo-send.py not found",
        }

    r = run_cmd([BREVO_SEND_SCRIPT], input_text=raw_message, timeout=40)
    return {
        "ok": r["ok"],
        "blocked": False,
        "returncode": r["returncode"],
        "stdout": r["stdout"],
        "stderr": r["stderr"],
    }


def send_credentials(
    username: str, recipients: list[str], password_text: str, wiki_url: str
) -> dict:
    mailbox_email = f"{username}@{DOMAIN}"
    results = []
    ok = True

    for rcpt in recipients:
        raw = build_credentials_message(rcpt, mailbox_email, password_text, wiki_url)
        r = send_via_brevo(raw)
        ok = ok and r["ok"]
        results.append({"recipient": rcpt, **r})

    return {"ok": ok, "results": results}


# =========================
# Auth tests
# =========================
def smtp_auth_test_swaks(
    email_addr: str, password: str, to_email: str | None = None
) -> dict:
    if not to_email:
        to_email = email_addr

    cmd = [
        "swaks",
        "--server",
        MAIL_HOST,
        "--port",
        "587",
        "--tls",
        "--auth",
        "LOGIN",
        "--auth-user",
        email_addr,
        "--auth-password",
        password,
        "--from",
        email_addr,
        "--to",
        to_email,
    ]
    return run_cmd(cmd, timeout=45)


def dovecot_auth_test(email_addr: str, password: str) -> dict:
    cmd = ["doveadm", "auth", "test", email_addr, password]
    return run_cmd(cmd, timeout=20)


# =========================
# Queue operations
# =========================
def get_queue_full() -> dict:
    return run_cmd(["postqueue", "-p"], timeout=30)


def flush_queue() -> dict:
    if is_safe_mode():
        return blocked_mutation("flush_queue")
    return run_cmd(["postqueue", "-f"], timeout=20)


def delete_queue_id(qid: str) -> dict:
    if is_safe_mode():
        return blocked_mutation("delete_queue_id")
    qid = qid.strip()
    if not re.fullmatch(r"[A-F0-9]+", qid, flags=re.IGNORECASE):
        return {"ok": False, "message": "Queue ID must match [A-F0-9]+"}
    return run_cmd(["postsuper", "-d", qid], timeout=20)


# =========================
# Usage + quota policy
# =========================
def read_quota_policy() -> dict:
    p = Path(QUOTA_POLICY_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_quota_policy(data: dict) -> None:
    Path(QUOTA_POLICY_FILE).write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_quota_policy(username: str, quota_mb: int) -> dict:
    if is_safe_mode():
        return blocked_mutation("set_quota_policy")

    qp = read_quota_policy()
    qp[username] = {"quota_mb": int(quota_mb), "updated_at": now_utc_iso()}
    write_quota_policy(qp)

    steps = [
        {
            "cmd": f"write {QUOTA_POLICY_FILE}",
            "started_at": now_utc_iso(),
            "finished_at": now_utc_iso(),
            "returncode": 0,
            "stdout": f"{username} quota={quota_mb}MB",
            "stderr": "",
            "ok": True,
        }
    ]

    if ENABLE_DOVECOT_USERDB_QUOTA_WRITES:
        try:
            dovep = Path(DOVECOT_USERDB_FILE)
            existing = (
                dovep.read_text(encoding="utf-8", errors="ignore").splitlines()
                if dovep.exists()
                else []
            )
            mail = f"{username}@{DOMAIN}"
            new_line = f"{mail}:{{PLAIN}}x::::::userdb_quota_rule=*:storage={quota_mb}M"
            out = []
            replaced = False
            for ln in existing:
                if ln.strip().startswith(f"{mail}:"):
                    out.append(new_line)
                    replaced = True
                else:
                    out.append(ln)
            if not replaced:
                out.append(new_line)
            dovep.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
            steps.append(
                {
                    "cmd": f"write {DOVECOT_USERDB_FILE}",
                    "started_at": now_utc_iso(),
                    "finished_at": now_utc_iso(),
                    "returncode": 0,
                    "stdout": "dovecot userdb updated",
                    "stderr": "",
                    "ok": True,
                }
            )
            steps.append(run_cmd(["systemctl", "reload", "dovecot"], timeout=20))
        except Exception as e:
            steps.append(
                {
                    "cmd": f"write {DOVECOT_USERDB_FILE}",
                    "started_at": now_utc_iso(),
                    "finished_at": now_utc_iso(),
                    "returncode": 1,
                    "stdout": "",
                    "stderr": f"{type(e).__name__}: {e}",
                    "ok": False,
                }
            )

    return {"ok": all(s["ok"] for s in steps), "steps": steps}


def mailbox_usage_mb(username: str) -> dict:
    maildir = Path("/home") / username / "Maildir"
    if not maildir.exists():
        return {"username": username, "usage_mb": 0, "exists": False}

    r = run_cmd(["du", "-sm", str(maildir)], timeout=20)
    if not r["ok"] or not r["stdout"]:
        return {
            "username": username,
            "usage_mb": 0,
            "exists": True,
            "error": r.get("stderr", "du failed"),
        }
    first = r["stdout"].split()[0]
    return {"username": username, "usage_mb": maybe_int(first, 0), "exists": True}


def all_usage_table(users: list[str]) -> list[dict]:
    qp = read_quota_policy()
    rows = []
    for u in users:
        usage = mailbox_usage_mb(u)
        quota_mb = maybe_int(
            qp.get(u, {}).get("quota_mb", DEFAULT_NEW_USER_QUOTA_MB),
            DEFAULT_NEW_USER_QUOTA_MB,
        )
        pct = round((usage["usage_mb"] / quota_mb) * 100, 2) if quota_mb > 0 else 0.0
        rows.append(
            {
                "username": u,
                "usage_mb": usage["usage_mb"],
                "quota_mb": quota_mb,
                "used_pct": pct,
                "maildir_exists": "✅" if usage.get("exists") else "❌",
            }
        )
    return rows


# =========================
# Login activity parsing
# =========================
def parse_dovecot_logins(max_lines: int = 5000) -> list[dict]:
    p = Path(MAIL_LOG_FILE)
    if not p.exists():
        return []

    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lines:]
    rows = []

    login_re = re.compile(
        r"dovecot: (\w+)-login: Login: user=<([^>]+)>, .*rip=([^, ]+)"
    )
    fail_patterns = [
        re.compile(
            r"dovecot: (\w+)-login: Disconnected \((auth failed.*?)\).*rip=([^, ]+).*user=<([^>]+)>"
        ),
        re.compile(
            r"dovecot: (\w+)-login: Aborted login \(auth failed.*?\): user=<([^>]+)>,.*rip=([^, ]+)"
        ),
    ]

    for ln in lines:
        m1 = login_re.search(ln)
        if m1:
            proto, user, ip = m1.groups()
            rows.append(
                {
                    "timestamp_raw": ln[:15],
                    "event": "login_success",
                    "proto": proto,
                    "user": user,
                    "ip": ip,
                    "line": ln,
                }
            )
            continue

        found_fail = False
        for fp in fail_patterns:
            m2 = fp.search(ln)
            if m2:
                g = m2.groups()
                if len(g) == 4:
                    proto, reason, ip, user = g
                else:
                    proto, user, ip = g
                    reason = "auth failed"
                rows.append(
                    {
                        "timestamp_raw": ln[:15],
                        "event": "login_failed",
                        "proto": proto,
                        "user": user,
                        "ip": ip,
                        "line": ln,
                        "reason": reason,
                    }
                )
                found_fail = True
                break

        if found_fail:
            continue

    return rows


# =========================
# Brevo API checks
# =========================
def read_brevo_key_from_script(path: str = BREVO_SEND_SCRIPT) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    m = re.search(r'BREVO_API_KEY\s*=\s*[\'"]([^\'"]+)[\'"]', text)
    if m:
        return m.group(1).strip()
    return ""


def brevo_api_key() -> str:
    k = os.getenv("BREVO_API_KEY", "").strip()
    if k:
        return k
    return read_brevo_key_from_script()


def masked_key(k: str) -> str:
    if not k:
        return "(missing)"
    if len(k) <= 12:
        return "*" * len(k)
    return f"{k[:8]}...{k[-4:]}"


def brevo_api_get(path: str) -> dict:
    key = brevo_api_key()
    if not key:
        return {
            "ok": False,
            "status": 0,
            "error": "Brevo API key missing",
            "data": None,
        }

    url = f"https://api.brevo.com{path}"
    req = request.Request(url)
    req.add_header("accept", "application/json")
    req.add_header("api-key", key)

    try:
        with request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(body) if body else {}
            return {"ok": True, "status": resp.status, "error": "", "data": data}
    except error.HTTPError as e:
        payload = ""
        try:
            payload = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": payload or str(e), "data": None}
    except Exception as e:
        return {
            "ok": False,
            "status": 0,
            "error": f"{type(e).__name__}: {e}",
            "data": None,
        }


def brevo_health_snapshot() -> dict:
    account = brevo_api_get("/v3/account")
    smtp = brevo_api_get("/v3/smtp/statistics?days=1")
    return {"account": account, "smtp_stats": smtp}


# =========================
# UI
# =========================
st.sidebar.header("Navigation")
page = st.sidebar.radio(
    "Go to",
    [
        "Health",
        "Mailboxes",
        "Lists & Forwards",
        "Auth Tests",
        "Queue",
        "Usage",
        "Logins",
        "Casdoor",
        "Brevo",
    ],
)

st.sidebar.markdown("---")
current_safe = read_safe_mode()
safe_toggle = st.sidebar.toggle("Safe Mode", value=current_safe)

if safe_toggle != current_safe:
    wr = write_safe_mode(safe_toggle)
    if wr.get("ok"):
        st.sidebar.success(f"Safe Mode {'ON' if safe_toggle else 'OFF'}")
    else:
        st.sidebar.error(f"Failed to persist mode: {wr.get('error', 'unknown error')}")

effective_safe = read_safe_mode()
st.sidebar.write(f"Effective mode: `{'SAFE' if effective_safe else 'UNSAFE'}`")
st.sidebar.write(f"Audit BCC: `{AUDIT_BCC_EMAIL}`")
st.sidebar.write(f"Credential sender: `{sender_email()}`")
st.sidebar.write(f"Quota policy file: `{QUOTA_POLICY_FILE}`")
st.sidebar.write(f"Brevo key source: `env or {BREVO_SEND_SCRIPT}`")

if effective_safe:
    st.warning(
        "SAFE MODE is ON: all mutating operations are simulated. "
        "No user/password/list/queue/quota changes are applied."
    )
else:
    st.error("UNSAFE MODE is ON: operations perform real server changes.", icon="⚠️")


# -------------------------
# Page: Health
# -------------------------
if page == "Health":
    st.subheader("Service health")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Postfix", get_service_status("postfix"))
    c2.metric("Dovecot", get_service_status("dovecot"))
    c3.metric("OpenDKIM", get_service_status("opendkim"))
    c4.metric("Queue count", get_queue_count())

    st.markdown("### TLS certificate")
    st.json(get_cert_dates())


# -------------------------
# Page: Mailboxes
# -------------------------
elif page == "Mailboxes":
    st.subheader("Mailboxes")

    if st.button("Refresh mailbox list"):
        list_mailboxes.clear()

    rows = list_mailboxes()
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Create mailbox (auto-generated password)")
    with st.form("create_mailbox_form"):
        username = st.text_input("Username (no domain)", placeholder="newuser")
        quota_mb = st.number_input(
            "Quota MB",
            min_value=100,
            max_value=10240,
            value=DEFAULT_NEW_USER_QUOTA_MB,
            step=100,
        )
        send_to = st.text_input("Send credentials to (comma-separated emails)")
        wiki_url = st.text_input("Wiki URL", value=DEFAULT_WIKI_URL)
        submit = st.form_submit_button("Create mailbox")

        if submit:
            uname = username.strip().lower()
            valid, msg = validate_username(uname)
            if not valid:
                st.error(msg)
            else:
                create_result = create_mailbox_autogen(uname, quota_mb=int(quota_mb))
                if create_result.get("blocked"):
                    st.warning(create_result["message"])
                elif create_result["ok"]:
                    st.success(f"Mailbox created: {create_result['email']}")
                    st.markdown("**Generated password:**")
                    st.code(create_result["generated_password"])
                    st.info("Copy this now; shown only once in clear text.")
                    list_mailboxes.clear()
                else:
                    st.error(create_result.get("message", "Create mailbox failed."))
                st.json(create_result)

                recipients = parse_emails(send_to)
                if create_result.get("ok") and recipients:
                    sr = send_credentials(
                        username=uname,
                        recipients=recipients,
                        password_text=create_result["generated_password"],
                        wiki_url=wiki_url.strip() or DEFAULT_WIKI_URL,
                    )
                    st.markdown("#### Credential email delivery")
                    for item in sr["results"]:
                        st.write(
                            f"- `{item['recipient']}` → **{pretty_status_label(item)}**"
                        )
                        with st.expander(f"Details: {item['recipient']}"):
                            st.json(item)

    st.markdown("---")
    st.markdown("### Per-user actions")

    usernames = [r["username"] for r in rows]
    if not usernames:
        st.info("No mailbox users found in /home.")
    else:
        selected_user = st.selectbox("Select mailbox user", options=usernames)

        c1, c2 = st.columns(2)

        with c1:
            st.markdown("#### Reset password (auto-generate)")
            with st.form("reset_password_form"):
                send_after_reset = st.checkbox(
                    "Send new credentials email after reset", value=False
                )
                reset_recipients_raw = st.text_input(
                    "Recipients (comma-separated)",
                    placeholder="user.personal@gmail.com, manager@example.com",
                )
                reset_wiki_url = st.text_input(
                    "Wiki URL", value=DEFAULT_WIKI_URL, key="reset_wiki_url"
                )
                reset_submit = st.form_submit_button("Reset password")

                if reset_submit:
                    rr = reset_password_autogen(selected_user)
                    if rr.get("blocked"):
                        st.warning(rr["message"])
                    elif rr["ok"]:
                        st.success(f"Password reset for {selected_user}")
                        st.markdown("**New password:**")
                        st.code(rr["new_password"])
                        st.info("Copy this now; shown only once in clear text.")
                    else:
                        st.error(rr.get("message", "Password reset failed."))
                    st.json(rr)

                    if rr.get("ok") and send_after_reset:
                        recipients = parse_emails(reset_recipients_raw)
                        if not recipients:
                            st.warning(
                                "Reset done, but no recipients provided for email."
                            )
                        else:
                            sr = send_credentials(
                                username=selected_user,
                                recipients=recipients,
                                password_text=rr["new_password"],
                                wiki_url=reset_wiki_url.strip() or DEFAULT_WIKI_URL,
                            )
                            st.markdown("##### Reset credential email delivery")
                            for item in sr["results"]:
                                st.write(
                                    f"- `{item['recipient']}` → **{pretty_status_label(item)}**"
                                )
                                with st.expander(f"Details: {item['recipient']}"):
                                    st.json(item)

        with c2:
            st.markdown("#### Delete mailbox")
            st.error("Danger zone: removes Linux user and home directory.")
            with st.form("delete_mailbox_form"):
                confirm_username = st.text_input(
                    f"Type '{selected_user}' to confirm deletion",
                    placeholder=selected_user,
                )
                delete_submit = st.form_submit_button("Delete mailbox")

                if delete_submit:
                    if confirm_username.strip() != selected_user:
                        st.error("Confirmation text does not match selected username.")
                    else:
                        dr = delete_mailbox(selected_user)
                        if dr.get("blocked"):
                            st.warning(dr["message"])
                        elif dr["ok"]:
                            st.success(f"Mailbox deleted: {selected_user}")
                            list_mailboxes.clear()
                        else:
                            st.error(dr.get("message", "Delete mailbox failed."))
                        st.json(dr)

    st.markdown("---")
    st.markdown("### Send credentials (manual)")
    with st.form("manual_send_form"):
        manual_user = st.text_input("Mailbox username", placeholder="akshat")
        recipients_raw = st.text_input(
            "Recipients (comma-separated)", placeholder="person1@example.com"
        )
        password_for_email = st.text_input(
            "Password text to include", placeholder="paste generated password"
        )
        wiki_url2 = st.text_input("Wiki URL", value=DEFAULT_WIKI_URL, key="wiki_url2")
        send_submit = st.form_submit_button("Send credentials")

        if send_submit:
            uname = manual_user.strip().lower()
            valid, msg = validate_username(uname)
            if not valid:
                st.error(msg)
            else:
                recipients = parse_emails(recipients_raw)
                if not recipients:
                    st.error("Provide at least one recipient.")
                elif not password_for_email.strip():
                    st.error("Provide password text.")
                else:
                    sr = send_credentials(
                        username=uname,
                        recipients=recipients,
                        password_text=password_for_email.strip(),
                        wiki_url=wiki_url2.strip() or DEFAULT_WIKI_URL,
                    )
                    st.markdown("#### Delivery status")
                    for item in sr["results"]:
                        st.write(
                            f"- `{item['recipient']}` → **{pretty_status_label(item)}**"
                        )
                        with st.expander(f"Details: {item['recipient']}"):
                            st.json(item)


# -------------------------
# Page: Lists & Forwards
# -------------------------
elif page == "Lists & Forwards":
    st.subheader("Lists & Forwards")
    v = parse_virtual_struct()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("List addresses", len(v["lists"]))
    c2.metric("Forwards", len(v["forwards"]))
    c3.metric("Tags", len(v["tags"]))
    c4.metric("Catch-all", "set" if v["catch_all"] else "missing")

    st.markdown("### Current lists")
    st.dataframe(pd.DataFrame(v["lists"]), use_container_width=True, hide_index=True)

    st.markdown("### Current forwards")
    st.dataframe(pd.DataFrame(v["forwards"]), use_container_width=True, hide_index=True)

    st.markdown("### Catch-all target")
    st.code(v["catch_all"] or "(not set)")

    st.markdown("### Tags")
    if v["tags"]:
        st.write(", ".join(v["tags"]))
    else:
        st.write("(none)")

    st.markdown("---")
    st.markdown("### Add / Remove list member")
    cl1, cl2 = st.columns(2)

    with cl1:
        with st.form("add_list_member_form"):
            list_addr = st.text_input("List address", placeholder=f"founders@{DOMAIN}")
            member_addr = st.text_input("Member email", placeholder=f"akshat@{DOMAIN}")
            tag = st.text_input("Optional tag", placeholder="founders")
            sub = st.form_submit_button("Add member")
            if sub:
                r = add_list_member(list_addr, member_addr, tag.strip())
                if r.get("ok"):
                    st.success(r.get("message", "Done"))
                else:
                    st.warning(
                        r.get("message", "Failed")
                        if r.get("blocked")
                        else r.get("message", "Failed")
                    )
                st.json(r)

    with cl2:
        with st.form("remove_list_member_form"):
            list_addr2 = st.text_input(
                "List address ", placeholder=f"founders@{DOMAIN}", key="list_addr2"
            )
            member_addr2 = st.text_input(
                "Member email ", placeholder=f"akshat@{DOMAIN}", key="member_addr2"
            )
            sub2 = st.form_submit_button("Remove member")
            if sub2:
                r = remove_list_member(list_addr2, member_addr2)
                if r.get("ok"):
                    st.success(r.get("message", "Done"))
                else:
                    st.warning(r.get("message", "Failed"))
                st.json(r)

    st.markdown("---")
    st.markdown("### Add / Remove external forward")
    cf1, cf2 = st.columns(2)

    with cf1:
        with st.form("add_forward_form"):
            src = st.text_input("Source address", placeholder=f"prayagraj@{DOMAIN}")
            dst = st.text_input("Forward target", placeholder="external@gmail.com")
            ftag = st.text_input("Optional tag ", placeholder="external-forwards")
            sub3 = st.form_submit_button("Add forward")
            if sub3:
                r = add_forward(src, dst, ftag.strip())
                if r.get("ok"):
                    st.success(r.get("message", "Done"))
                else:
                    st.warning(r.get("message", "Failed"))
                st.json(r)

    with cf2:
        with st.form("remove_forward_form"):
            src2 = st.text_input(
                "Source address ", placeholder=f"prayagraj@{DOMAIN}", key="src2"
            )
            dst2 = st.text_input(
                "Forward target ", placeholder="external@gmail.com", key="dst2"
            )
            sub4 = st.form_submit_button("Remove forward")
            if sub4:
                r = remove_forward(src2, dst2)
                if r.get("ok"):
                    st.success(f"Removed entries: {r.get('removed', 0)}")
                else:
                    st.warning("Failed")
                st.json(r)

    st.markdown("---")
    st.markdown("### Add / Remove tag marker")
    ct1, ct2 = st.columns(2)

    with ct1:
        with st.form("add_tag_form"):
            t1 = st.text_input("Tag name", placeholder="volunteers")
            s1 = st.form_submit_button("Add tag")
            if s1:
                r = add_tag(t1)
                if r.get("ok"):
                    st.success(r.get("message", "Done"))
                else:
                    st.warning(r.get("message", "Failed"))
                st.json(r)

    with ct2:
        with st.form("remove_tag_form"):
            t2 = st.text_input("Tag name ", placeholder="volunteers", key="t2")
            s2 = st.form_submit_button("Remove tag marker")
            if s2:
                r = remove_tag(t2)
                if r.get("ok"):
                    st.success(f"Removed tag markers: {r.get('removed', 0)}")
                else:
                    st.warning("Failed")
                st.json(r)

    st.markdown("---")
    st.markdown("### Raw virtual file preview")
    st.code("\n".join(read_virtual_lines())[:15000])


# -------------------------
# Page: Auth Tests
# -------------------------
elif page == "Auth Tests":
    st.subheader("Authentication tests")

    st.markdown("### SMTP AUTH test (swaks)")
    with st.form("smtp_auth_form"):
        email_a = st.text_input("Email", placeholder=f"hello@{DOMAIN}")
        pass_a = st.text_input("Password", type="password")
        to_a = st.text_input("Test recipient", placeholder=f"hello@{DOMAIN}")
        run_a = st.form_submit_button("Run SMTP test")
        if run_a:
            if not email_a.strip() or not pass_a:
                st.error("Email and password required.")
            else:
                r = smtp_auth_test_swaks(
                    email_a.strip(), pass_a, to_a.strip() or email_a.strip()
                )
                if r["ok"]:
                    st.success("SMTP AUTH test succeeded")
                else:
                    st.error("SMTP AUTH test failed")
                st.json(r)

    st.markdown("### Dovecot auth test")
    with st.form("dovecot_auth_form"):
        email_b = st.text_input("Email ", placeholder=f"hello@{DOMAIN}")
        pass_b = st.text_input("Password ", type="password")
        run_b = st.form_submit_button("Run Dovecot auth test")
        if run_b:
            if not email_b.strip() or not pass_b:
                st.error("Email and password required.")
            else:
                r = dovecot_auth_test(email_b.strip(), pass_b)
                if r["ok"]:
                    st.success("Dovecot auth test succeeded")
                else:
                    st.error("Dovecot auth test failed")
                st.json(r)


# -------------------------
# Page: Queue
# -------------------------
elif page == "Queue":
    st.subheader("Mail queue")

    c1, c2 = st.columns(2)
    c1.metric("Queue count", get_queue_count())

    if c2.button("Refresh queue"):
        pass

    q = get_queue_full()
    st.markdown("### postqueue -p")
    st.code((q["stdout"] or q["stderr"] or "(no output)")[:25000])

    st.markdown("---")
    st.markdown("### Queue actions")
    qa1, qa2 = st.columns(2)

    with qa1:
        if st.button("Flush queue (postqueue -f)"):
            r = flush_queue()
            st.json(r)

    with qa2:
        with st.form("delete_queue_id_form"):
            qid = st.text_input("Delete queue ID", placeholder="AB12CD34E")
            s = st.form_submit_button("Delete ID")
            if s:
                r = delete_queue_id(qid)
                st.json(r)


# -------------------------
# Page: Usage
# -------------------------
elif page == "Usage":
    st.subheader("Mailbox usage + quota policy")

    users = [r["username"] for r in list_mailboxes()]
    usage_rows = all_usage_table(users)
    dfu = pd.DataFrame(usage_rows)
    st.dataframe(dfu, use_container_width=True, hide_index=True)

    total_usage = sum([x.get("usage_mb", 0) for x in usage_rows])
    st.metric("Total Maildir usage (MB)", total_usage)

    st.markdown("### Resize quota")
    with st.form("resize_quota_form"):
        user_q = st.selectbox("User", options=users if users else [])
        new_q = st.number_input(
            "New quota MB",
            min_value=100,
            max_value=20480,
            value=DEFAULT_NEW_USER_QUOTA_MB,
            step=100,
        )
        sub_q = st.form_submit_button("Set quota")
        if sub_q:
            if not user_q:
                st.error("No user selected.")
            else:
                r = set_quota_policy(user_q, int(new_q))
                if r.get("blocked"):
                    st.warning(r["message"])
                elif r["ok"]:
                    st.success(f"Quota policy updated: {user_q} -> {int(new_q)}MB")
                else:
                    st.error("Failed to set quota policy")
                st.json(r)

    st.markdown("### Quota implementation notes")
    st.info(
        "This app always stores quota targets in mail-quota-policy.json. "
        "Actual Dovecot enforcement requires Dovecot config wired to userdb quota rules. "
        "Set ENABLE_DOVECOT_USERDB_QUOTA_WRITES=True only if /etc/dovecot/users is active userdb."
    )


# -------------------------
# Page: Logins
# -------------------------
elif page == "Logins":
    st.subheader("Dovecot login activity")

    max_lines = st.slider(
        "Log lines to scan", min_value=100, max_value=20000, value=5000, step=100
    )
    rows = parse_dovecot_logins(max_lines=max_lines)

    if not rows:
        st.warning("No parsed login events found (or log file missing).")
    else:
        dfl = pd.DataFrame(rows)
        st.dataframe(dfl, use_container_width=True, hide_index=True)

        st.markdown("### Filters")
        users = sorted(list(set([r.get("user", "") for r in rows if r.get("user")])))
        chosen_user = st.selectbox("Filter by user", options=["(all)"] + users)
        chosen_event = st.selectbox(
            "Filter by event", options=["(all)", "login_success", "login_failed"]
        )

        filtered = rows
        if chosen_user != "(all)":
            filtered = [r for r in filtered if r.get("user") == chosen_user]
        if chosen_event != "(all)":
            filtered = [r for r in filtered if r.get("event") == chosen_event]

        st.markdown(f"Filtered rows: **{len(filtered)}**")
        st.dataframe(pd.DataFrame(filtered), use_container_width=True, hide_index=True)

# -------------------------
# Page: Casdoor
# -------------------------
elif page == "Casdoor":
    st.subheader("Casdoor IAM")
    st.markdown(
        "Open the Casdoor admin UI: "
        "[https://auth.gobitsnbytes.org](https://auth.gobitsnbytes.org)"
    )
    st.info(
        "If you see a TLS warning, ensure the auth subdomain has its own "
        "Let’s Encrypt cert and DNS points to this VPS."
    )


# -------------------------
# Page: Brevo
# -------------------------
elif page == "Brevo":
    st.subheader("Brevo API health + credits/quota")

    k = brevo_api_key()
    if not k:
        st.error("Brevo API key not found in env or brevo-send.py")
    else:
        st.success(f"Brevo key detected: {masked_key(k)}")

    if st.button("Refresh Brevo status"):
        pass

    snap = brevo_health_snapshot()

    st.markdown("### /v3/account")
    if snap["account"]["ok"]:
        st.success(f"Account API OK (HTTP {snap['account']['status']})")
    else:
        st.error(f"Account API failed (HTTP {snap['account']['status']})")
    st.json(snap["account"])

    st.markdown("### /v3/smtp/statistics?days=1")
    if snap["smtp_stats"]["ok"]:
        st.success(f"SMTP stats API OK (HTTP {snap['smtp_stats']['status']})")
    else:
        st.warning(
            f"SMTP stats API failed/unsupported (HTTP {snap['smtp_stats']['status']})"
        )
    st.json(snap["smtp_stats"])

    st.markdown("### Brevo send script quick check")
    bs = run_cmd(["python3", "-m", "py_compile", BREVO_SEND_SCRIPT], timeout=10)
    if bs["ok"]:
        st.success("brevo-send.py syntax OK")
    else:
        st.error("brevo-send.py syntax check failed")
    st.json(bs)

    st.markdown("### Quick interpretation")
    st.info(
        "If /v3/account returns OK, API is reachable with current key. "
        "Use smtp statistics/account payload to monitor usage and limits exposed by Brevo."
    )
