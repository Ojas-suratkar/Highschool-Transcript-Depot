import os


class Settings:
    """Minimal environment-backed settings to avoid requiring pydantic-settings at runtime.
    Values are read from environment variables and cast where appropriate.
    """
    ENV: str = os.environ.get('ENV', 'development')
    DATABASE_URL: str = os.environ.get('DATABASE_URL')
    JWT_SECRET: str = os.environ.get('JWT_SECRET', 'change-me')
    JWT_ALGORITHM: str = os.environ.get('JWT_ALGORITHM', 'HS256')
    JWT_EXP_SECONDS: int = int(os.environ.get('JWT_EXP', '3600'))

    OTP_TTL_SECONDS: int = int(os.environ.get('OTP_TTL_SECONDS', '600'))
    OTP_RESEND_COOLDOWN_SECONDS: int = int(os.environ.get('OTP_RESEND_COOLDOWN_SECONDS', '600'))
    OTP_MAX_ATTEMPTS: int = int(os.environ.get('OTP_MAX_ATTEMPTS', '3'))
    OTP_REQUESTS_PER_HOUR: int = int(os.environ.get('OTP_REQUESTS_PER_HOUR', '5'))

    DELIVERY_MODE: str = os.environ.get('DELIVERY_MODE', 'mock')

    # Optional SMTP settings (use SMTP delivery instead of Brevo API)
    SMTP_HOST: str | None = os.environ.get('SMTP_HOST')
    SMTP_PORT: int | None = int(os.environ.get('SMTP_PORT')) if os.environ.get('SMTP_PORT') else None
    SMTP_USER: str | None = os.environ.get('SMTP_USER')
    SMTP_PASS: str | None = os.environ.get('SMTP_PASS')
    SMTP_USE_TLS: bool = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')

    # MailerSend settings (if you prefer MailerSend API over Brevo)
    MAILERSEND_API_KEY: str | None = os.environ.get('MAILERSEND_API_KEY')
    MAILERSEND_DOMAIN: str | None = os.environ.get('MAILERSEND_DOMAIN')
    # MailerSend sender configuration
    MAILERSEND_SENDER_EMAIL: str | None = os.environ.get('MAILERSEND_SENDER_EMAIL')
    MAILERSEND_SENDER_NAME: str | None = os.environ.get('MAILERSEND_SENDER_NAME')
    # Generic fallbacks used by the code to choose a sender
    SENDER_EMAIL: str | None = os.environ.get('MAILERSEND_SENDER_EMAIL') or os.environ.get('SENDER_EMAIL')
    SENDER_NAME: str = os.environ.get('MAILERSEND_SENDER_NAME') or os.environ.get('SENDER_NAME') or 'No Reply'
    # Sender email addresses (support older BREVO env name and MailerSend name)
    # (removed BREVO vars) -- MailerSend is the only supported provider in this config


settings = Settings()
