import os
import email
import imaplib
from dotenv import load_dotenv

load_dotenv("apps/api/.env")

user = os.environ.get("GMAIL_USER")
app_pw = os.environ.get("GMAIL_APP_PASSWORD")

client = imaplib.IMAP4_SSL("imap.gmail.com")
client.login(user, app_pw)
client.select("INBOX", readonly=True)

status, data = client.search(None, '(SUBJECT "Security code for your application")')
if status == "OK" and data and data[0]:
    uids = data[0].split()
    latest_uid = uids[-1]
    s, msg_data = client.fetch(latest_uid, '(RFC822)')
    if s == "OK":
        msg = email.message_from_bytes(msg_data[0][1])
        body = ""
        if msg.is_multipart():
            for p in msg.walk():
                if p.get_content_type() in ("text/plain", "text/html"):
                    pl = p.get_payload(decode=True)
                    if pl:
                        body += pl.decode(p.get_content_charset() or "utf-8", errors="replace")
        else:
            pl = msg.get_payload(decode=True)
            if pl:
                body += pl.decode(msg.get_content_charset() or "utf-8", errors="replace")
        
        print("=== LATEST SECURITY CODE EMAIL BODY ===")
        print(body)

client.logout()
