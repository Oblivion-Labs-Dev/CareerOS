import os
import re
import email
from email.header import decode_header
import imaplib
from dotenv import load_dotenv

load_dotenv("apps/api/.env")

user = os.environ.get("GMAIL_USER")
app_pw = os.environ.get("GMAIL_APP_PASSWORD")

print(f"Connecting to Gmail as {user}...")
client = imaplib.IMAP4_SSL("imap.gmail.com")
client.login(user, app_pw)
client.select("INBOX", readonly=True)

# Search recent emails from greenhouse or with verification in subject
status, data = client.search(None, '(OR FROM "greenhouse.io" SUBJECT "verification")')
if status == "OK" and data and data[0]:
    uids = data[0].split()
    print(f"Found {len(uids)} matching verification emails!")
    # inspect latest 5
    for uid in uids[-5:]:
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
            
            print(f"\n--- Email UID {uid.decode()} ---")
            print(f"Date: {date_}")
            print(f"From: {from_}")
            print(f"Subject: {subject}")
            print(f"Snippet: {body[:300]}")
            
            # Find 8-char codes or code patterns
            codes = re.findall(r"\b[A-Za-z0-9]{8}\b", body)
            print(f"Potential 8-char codes: {codes[:5]}")
else:
    print("No greenhouse verification emails found in search, testing general recent emails...")
    status, data = client.search(None, 'ALL')
    uids = data[0].split()
    print(f"Total inbox emails: {len(uids)}. Latest 3:")
    for uid in uids[-3:]:
        s, msg_data = client.fetch(uid, '(RFC822)')
        if s == "OK":
            msg = email.message_from_bytes(msg_data[0][1])
            print("Subject:", msg.get("Subject"))
            print("From:", msg.get("From"))

client.logout()
