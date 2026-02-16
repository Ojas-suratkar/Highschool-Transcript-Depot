import os
import asyncio
from email.message import EmailMessage
import aiosmtplib


class EmailNotifier:
    def __init__(self):
        self.host = os.environ.get('SMTP_HOST')
        self.port = int(os.environ.get('SMTP_PORT', '587'))
        self.user = os.environ.get('SMTP_USER')
        self.password = os.environ.get('SMTP_PASSWORD')
        self.from_addr = os.environ.get('SMTP_FROM')

    async def send(self, to: str, message: str):
        if not self.host:
            # no-op in dev
            print(f"EMAIL (noop) to={to}: {message}")
            return
        msg = EmailMessage()
        msg['From'] = self.from_addr
        msg['To'] = to
        msg['Subject'] = 'Your OTP Code'
        msg.set_content(message)

        await aiosmtplib.send(msg, hostname=self.host, port=self.port, username=self.user, password=self.password, start_tls=True)
