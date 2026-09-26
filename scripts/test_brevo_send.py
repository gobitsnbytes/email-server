"""Run: python scripts/test_brevo_send.py"""
import email
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("brevo_send", Path(__file__).with_name("brevo-send.py"))
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)

msg = email.message_from_string("To: A@x.com, b@x.com\nCc: c@y.com\nSubject: s\n\nbody")
assert bs.split_recipients(msg, ["a@x.com", "B@x.com", "c@y.com", "d@z.com", "a@x.com"]) == (
    ["a@x.com", "b@x.com"], ["c@y.com"], ["d@z.com"])
# only a Cc recipient on this delivery: promoted to "to", no hidden recipient exposed
assert bs.split_recipients(msg, ["c@y.com", "d@z.com"]) == (["c@y.com"], [], ["d@z.com"])
assert bs.split_recipients(msg, ["d@z.com"]) == (["d@z.com"], [], [])
print("ok")
