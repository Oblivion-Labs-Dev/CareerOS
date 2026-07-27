from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.gmail_sender import GmailSender, SendEmailPayload, build_gmail_sender

client = TestClient(app)


def test_build_gmail_sender_requires_credentials() -> None:
    with pytest.raises(ValueError):
        build_gmail_sender("", "")


def test_send_email_payload_requires_body() -> None:
    sender = GmailSender(user="test@gmail.com", app_password="secret")
    with pytest.raises(ValueError, match="Either text or html"):
        sender.send(SendEmailPayload(to="friend@example.com", subject="Hi"))


@patch("app.services.gmail_sender.smtplib.SMTP_SSL")
def test_gmail_sender_send_success(mock_smtp_cls: MagicMock) -> None:
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    smtp.send_message.return_value = {}
    mock_smtp_cls.return_value = smtp

    sender = GmailSender(user="test@gmail.com", app_password="secret")
    result = sender.send(
        SendEmailPayload(
            to="friend@example.com",
            subject="Hello",
            text="Body",
        )
    )

    assert "messageId" in result
    smtp.login.assert_called_once_with("test@gmail.com", "secret")
    smtp.send_message.assert_called_once()


def test_email_verify_returns_not_configured_when_unconfigured() -> None:
    with patch("app.routers.api.settings") as mock_settings:
        mock_settings.gmail_user = ""
        mock_settings.gmail_app_password = ""
        response = client.get("/email/verify")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["success"] is False
