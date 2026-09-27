"""Small checks for the admin's mailbox listing and creation guards."""

import ast
import pathlib
import tempfile
from types import SimpleNamespace


SOURCE = pathlib.Path(__file__).resolve().parents[1] / "mail-server-backend.py"


def load_function(name, namespace):
    node = next(n for n in ast.parse(SOURCE.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[name]


def check():
    with tempfile.TemporaryDirectory() as directory:
        home = pathlib.Path(directory)
        for name in ("active", "orphan"):
            (home / name / "Maildir").mkdir(parents=True)

        def getpwnam(name):
            if name == "orphan":
                raise KeyError(name)
            return SimpleNamespace(pw_uid=1001, pw_shell="/usr/sbin/nologin", pw_dir=str(home / name))

        namespace = {
            "Path": lambda path: home if path == "/home" else pathlib.Path(path),
            "pwd": SimpleNamespace(getpwnam=getpwnam),
            "DOMAIN": "example.org",
            "load_virtual_map": lambda: {"active@example.org": "active"},
        }
        rows = load_function("list_mailboxes", namespace)()
        assert [row["username"] for row in rows] == ["active"]

        calls = []
        namespace.update({
            "is_safe_mode": lambda: False,
            "validate_username": lambda name: (True, ""),
            "user_exists": lambda name: False,
            "generate_password": lambda: "unused",
            "safe_file_backup": lambda path: {"ok": True, "backup": path},
            "POSTFIX_VIRTUAL_FILE": "/etc/postfix/virtual",
            "DEFAULT_NEW_USER_QUOTA_MB": 512,
            "now_utc_iso": lambda: "now",
            "run_cmd": lambda cmd, **kwargs: calls.append(cmd) or {"ok": False},
        })
        create = load_function("create_mailbox_autogen", namespace)
        assert not create("orphan")["ok"] and not calls
        assert not create("newuser")["ok"]
        assert calls == [["useradd", "-m", "-s", "/usr/sbin/nologin", "newuser"]]


if __name__ == "__main__":
    check()
    print("mailbox admin checks passed")
