"""Gmail SMTP sending — migrated from Arsenal packages/backend/src/gateways/gmail.ts."""

from __future__ import annotations

import mimetypes
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


class EmailAttachment(BaseModel):
    filename: str
    content: str | bytes | None = None
    path: str | None = None
    content_type: str | None = None


class SendEmailPayload(BaseModel):
    to: EmailStr | list[EmailStr]
    cc: EmailStr | list[EmailStr] | None = None
    bcc: EmailStr | list[EmailStr] | None = None
    subject: str = Field(min_length=1)
    text: str | None = None
    html: str | None = None
    attachments: list[EmailAttachment] | None = None

    @field_validator("to", "cc", "bcc", mode="before")
    @classmethod
    def normalize_recipients(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, str):
            return value
        return list(value)


class GmailSender:
    def __init__(self, user: str, app_password: str) -> None:
        if not user or not app_password:
            raise ValueError("Gmail credentials (user, app_password) are required.")
        self.user = user
        self.app_password = app_password

    def send(self, payload: SendEmailPayload) -> dict[str, str]:
        message = self._build_message(payload)
        try:
            with self._smtp() as smtp:
                smtp.login(self.user, self.app_password)
                refused = smtp.send_message(message)
            if refused:
                raise RuntimeError(f"SMTP refused recipients: {refused}")
            return {"messageId": message.get("Message-ID", "")}
        except Exception as exc:
            raise RuntimeError(f"Failed to send email via Gmail SMTP: {exc}") from exc

    def verify_connection(self) -> bool:
        try:
            with self._smtp() as smtp:
                smtp.login(self.user, self.app_password)
                smtp.noop()
            return True
        except Exception:
            return False

    def _smtp(self) -> smtplib.SMTP_SSL:
        return smtplib.SMTP_SSL("smtp.gmail.com", 465)

    def _build_message(self, payload: SendEmailPayload) -> MIMEMultipart:
        if not payload.text and not payload.html:
            raise ValueError("Either text or html body is required.")

        message = MIMEMultipart()
        message["From"] = self.user
        message["To"] = self._format_addresses(payload.to)
        if payload.cc:
            message["Cc"] = self._format_addresses(payload.cc)
        if payload.bcc:
            message["Bcc"] = self._format_addresses(payload.bcc)
        message["Subject"] = payload.subject

        if payload.text:
            message.attach(MIMEText(payload.text, "plain", "utf-8"))
        if payload.html:
            message.attach(MIMEText(payload.html, "html", "utf-8"))

        for attachment in payload.attachments or []:
            message.attach(self._build_attachment(attachment))

        return message

    @staticmethod
    def _format_addresses(value: EmailStr | list[EmailStr]) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    @staticmethod
    def _build_attachment(attachment: EmailAttachment) -> MIMEBase:
        content_type = attachment.content_type
        if attachment.path:
            path = Path(attachment.path)
            if not path.exists():
                raise ValueError(f"Attachment not found: {attachment.path}")
            raw = path.read_bytes()
            if not content_type:
                guessed, _ = mimetypes.guess_type(path.name)
                content_type = guessed or "application/octet-stream"
            filename = attachment.filename or path.name
        elif attachment.content is not None:
            raw = attachment.content.encode("utf-8") if isinstance(attachment.content, str) else attachment.content
            content_type = content_type or "application/octet-stream"
            filename = attachment.filename
        else:
            raise ValueError(f"Attachment '{attachment.filename}' requires content or path.")

        maintype, _, subtype = content_type.partition("/")
        part = MIMEBase(maintype, subtype or "octet-stream")
        part.set_payload(raw)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        return part


def build_gmail_sender(user: str | None, app_password: str | None) -> GmailSender:
    if not user or not app_password:
        raise ValueError("GMAIL_USER and GMAIL_APP_PASSWORD must be configured.")
    return GmailSender(user=user, app_password=app_password)
