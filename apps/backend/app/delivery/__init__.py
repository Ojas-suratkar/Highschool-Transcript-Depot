import os
from typing import Optional

from ..notifications.email_notifier import EmailNotifier
from ..notifications.sms_notifier import SMSNotifier


class MockAdapter:
    def __init__(self):
        pass

    async def send(self, destination: str, message: str, channel: str = 'email'):
        # Mock adapter: no external host, prints to logs and returns
        print(f"[MOCK DELIVERY] channel={channel} to={destination}: {message}")
        return True


class DeliveryManager:
    """Provider-agnostic delivery manager.

    Modes (set DELIVERY_MODE):
      - mock (default): prints OTPs to logs and does not require SMTP/SMS provider
      - email_to_sms: uses EmailNotifier to send to carrier gateway
      - kannel: uses SMSNotifier which can call an HTTP gateway
      - smtp: uses EmailNotifier to send real emails (requires SMTP_HOST etc.)
    """

    def __init__(self):
        self.mode = os.environ.get('DELIVERY_MODE', 'mock')
        self.email = EmailNotifier()
        self.sms = SMSNotifier()
        self.mock = MockAdapter()

    async def send(self, destination: str, message: str, channel: str = 'email') -> Optional[bool]:
        if self.mode == 'mock':
            return await self.mock.send(destination, message, channel)
        if self.mode == 'smtp':
            # real SMTP send
            return await self.email.send(destination, message)
        if self.mode == 'email_to_sms':
            return await self.sms.send(destination, message)
        if self.mode == 'kannel':
            return await self.sms.send(destination, message)
        # unknown mode, fallback to mock
        return await self.mock.send(destination, message, channel)
