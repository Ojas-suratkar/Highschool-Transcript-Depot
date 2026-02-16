from __future__ import annotations
from typing import Protocol
import os
import httpx
import asyncio
import smtplib
from email.message import EmailMessage
from ..core.config import settings
try:
    from mailersend import MailerSendClient, EmailBuilder
    HAS_MAILERSEND = True
except Exception:
    HAS_MAILERSEND = False


class EmailSender(Protocol):
    async def send(self, to_email: str, subject: str, body: str) -> None:
        ...


# Brevo removed: use MailerSend or SMTP instead


class MockEmailSender:
    def __init__(self):
        pass

    async def send(self, to_email: str, subject: str, body: str) -> None:
        print(f"[MOCK EMAIL] to={to_email} subject={subject}\n{body}")


class SMTPEmailSender:
    """Simple SMTP sender that runs blocking smtplib sends in a thread."""
    def __init__(self):
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT or 587
        self.user = settings.SMTP_USER
        self.password = settings.SMTP_PASS
        self.use_tls = settings.SMTP_USE_TLS
        # fallback sender email (From)
        self.sender_email = settings.SENDER_EMAIL or f'no-reply@{os.environ.get("HOSTNAME","localhost")}'
        self.sender_name = settings.SENDER_NAME

    async def send(self, to_email: str, subject: str, body: str) -> None:
        if not self.host:
            raise RuntimeError('SMTP_HOST not configured')

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = f"{self.sender_name} <{self.sender_email}>"
        msg['To'] = to_email
        msg.set_content('This is an HTML email. Please view in an HTML-capable client.')
        msg.add_alternative(body, subtype='html')

        # run blocking send in thread
        await asyncio.to_thread(self._send_sync, msg)

    def _send_sync(self, msg: EmailMessage) -> None:
        try:
            if self.use_tls:
                # connect, start TLS, then login
                with smtplib.SMTP(self.host, self.port, timeout=10) as s:
                    s.ehlo()
                    s.starttls()
                    s.ehlo()
                    if self.user and self.password:
                        s.login(self.user, self.password)
                    s.send_message(msg)
            else:
                # try SSL if port indicates, otherwise plain
                if self.port == 465:
                    with smtplib.SMTP_SSL(self.host, self.port, timeout=10) as s:
                        if self.user and self.password:
                            s.login(self.user, self.password)
                        s.send_message(msg)
                else:
                    with smtplib.SMTP(self.host, self.port, timeout=10) as s:
                        if self.user and self.password:
                            s.login(self.user, self.password)
                        s.send_message(msg)
            print(f"[SMTP] sent to={msg['To']} subject={msg['Subject']}")
        except Exception as e:
            print(f"[SMTP] send failed: {e}")
            raise


class MailerSendSender:
    def __init__(self):
        if not HAS_MAILERSEND:
            raise RuntimeError('mailersend package not installed')
        self.api_key = settings.MAILERSEND_API_KEY
        self.domain = settings.MAILERSEND_DOMAIN
        if not self.api_key:
            raise RuntimeError('MAILERSEND_API_KEY not configured')
        self.client = MailerSendClient(self.api_key)
        # sender email/name (fallbacks)
        self.sender_email = settings.SENDER_EMAIL or f'no-reply@{self.domain or "mailersend.local"}'
        self.sender_name = settings.SENDER_NAME

    async def send(self, to_email: str, subject: str, body: str) -> None:
        # mailersend SDK is blocking; run in thread
        await asyncio.to_thread(self._send_sync, to_email, subject, body)

    def _send_sync(self, to_email: str, subject: str, body: str) -> None:
        try:
            email = (
                EmailBuilder()
                .from_email(self.sender_email, self.sender_name)
                .to_many([{"email": to_email}])
                .subject(subject)
                .html(body)
                .text('Please view this email in HTML.')
                .build()
            )
            resp = self.client.emails.send(email)
            # MailerSendClient returns an object with message_id or similar
            print(
                f"[MAILERSEND] sent to={to_email} resp={getattr(resp, 'message_id', getattr(resp, 'id', None))}"
            )
        except Exception as e:
            print(f"[MAILERSEND] send failed: {e}")
            raise


# End of file
