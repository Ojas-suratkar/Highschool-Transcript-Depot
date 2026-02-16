import os
from ..notifications.email_notifier import EmailNotifier


class SMSNotifier:
    """Open-source-friendly SMS notifier.

    Strategy (choose via env var SMS_GATEWAY):
      - email_to_sms: send SMS via carrier email-to-SMS gateway (set SMS_EMAIL_GATEWAY_DOMAIN)
      - kannel: use an HTTP Kannel gateway (set KANNEL_URL)
      - noop (default): just print

    Notes:
    - email-to-SMS requires knowing the carrier gateway domain (e.g. txt.att.net). This is a low-cost open approach for testing.
    - Kannel or Jasmin are open-source SMS gateways you can self-host for bulk/production.
    """

    def __init__(self):
        self.gateway = os.environ.get('SMS_GATEWAY', 'noop')
        self.email_gateway_domain = os.environ.get('SMS_EMAIL_GATEWAY_DOMAIN')
        self.kannel_url = os.environ.get('KANNEL_URL')
        self.email_notifier = EmailNotifier()

    async def send(self, to: str, message: str):
        if self.gateway == 'email_to_sms':
            if not self.email_gateway_domain:
                print(f"SMS (noop – missing SMS_EMAIL_GATEWAY_DOMAIN) to={to}: {message}")
                return
            # map phone number to carrier email address
            to_addr = f"{to}@{self.email_gateway_domain}"
            await self.email_notifier.send(to_addr, message)
            return

        if self.gateway == 'kannel':
            if not self.kannel_url:
                print(f"SMS (noop – missing KANNEL_URL) to={to}: {message}")
                return
            # import httpx only when needed to avoid hard dependency
            import httpx
            async with httpx.AsyncClient() as client:
                data = {'to': to, 'text': message}
                r = await client.post(self.kannel_url, data=data)
                r.raise_for_status()
            return

        # default noop
        print(f"SMS (noop) to={to}: {message}")
