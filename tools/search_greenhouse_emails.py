import os
import email
from email.header import decode_header
import imaplib
import re
from dotenv import load_dotenv

load_dotenv("apps/api/.env")

user = os.environ.get("GMAIL_USER")
app_pw = os.environ.get("GMAIL_APP_PASSWORD")

client = imaplib.IMAP4_SSL("imap.gmail.com")
client.login(user, app_pw)
client.select("INBOX", readonly=True)

# Search all emails with greenhouse
status, data = client.search(None, '(OR (OR FROM "greenhouse" SUBJECT "greenhouse") (OR BODY "greenhouse" SUBJECT "verification"))')
if status == "OK" and data and data[0]:
    uids = data[0].split()
    print(f"Total found: {len(uids)}")
    for uid in uids[-10:]:
        s, msg_data = client.fetch(uid, '(RFC822)')
        if s == "OK":
            msg = email.message_from_bytes(msg_data[0][1])
            subject = ""
            for part, enc in decode_header(msg.get("Subject", "")):
                subject += part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else str(part)
            from_ = msg.get("From", "")
            date_ = msg.get("Date", "")
            
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
            
            print(f"Date: {date_} | From: {from_} | Subject: {subject}")
            print(f"Body preview: {body[:250]}\n---")

client.logout()
