import os


class Settings:
    """Minimal environment-backed settings to avoid requiring pydantic-settings at runtime.
    Values are read from environment variables and cast where appropriate.
    """
    ENV: str = os.environ.get('ENV', 'development')
    DATABASE_URL: str = os.environ.get('DATABASE_URL')
    JWT_SECRET: str = os.environ.get('JWT_SECRET', 'change-me')
    JWT_ALGORITHM: str = os.environ.get('JWT_ALGORITHM', 'HS256')
    JWT_EXP_SECONDS: int = int(os.environ.get('JWT_EXP', '7200'))

    OTP_TTL_SECONDS: int = int(os.environ.get('OTP_TTL_SECONDS', '600'))
    OTP_RESEND_COOLDOWN_SECONDS: int = int(os.environ.get('OTP_RESEND_COOLDOWN_SECONDS', '600'))
    OTP_MAX_ATTEMPTS: int = int(os.environ.get('OTP_MAX_ATTEMPTS', '3'))
    OTP_REQUESTS_PER_HOUR: int = int(os.environ.get('OTP_REQUESTS_PER_HOUR', '5'))
    # Debug helper: returns the OTP in auth API responses. This is a serious
    # auth-bypass risk and is HARD-DISABLED in production regardless of the env
    # var — it can only be enabled when ENV is not 'production'.
    OTP_DEBUG_RETURN_IN_RESPONSE: bool = (
        os.environ.get('OTP_DEBUG_RETURN_IN_RESPONSE', 'false').lower() in ('1', 'true', 'yes')
        and os.environ.get('ENV', 'development').lower() != 'production'
    )

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

    FRONTEND_ORIGIN: str = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:5173')

    # Microsoft Entra ID (Azure AD) SSO
    MICROSOFT_CLIENT_ID: str | None = os.environ.get('MICROSOFT_CLIENT_ID')
    MICROSOFT_CLIENT_SECRET: str | None = os.environ.get('MICROSOFT_CLIENT_SECRET')
    MICROSOFT_TENANT_ID: str | None = os.environ.get('MICROSOFT_TENANT_ID')
    MICROSOFT_REDIRECT_URI: str = os.environ.get(
        'MICROSOFT_REDIRECT_URI', 'http://localhost:8000/api/auth/microsoft/callback'
    )


settings = Settings()

# Fail-fast / warn on insecure production configuration.
if settings.ENV.lower() == 'production':
    import logging as _logging
    _log = _logging.getLogger("app.config")
    if settings.JWT_SECRET in (None, '', 'change-me'):
        raise RuntimeError(
            "JWT_SECRET is unset or the insecure default in production. "
            "Set a strong JWT_SECRET environment variable."
        )
    if settings.OTP_DEBUG_RETURN_IN_RESPONSE:
        _log.warning("OTP_DEBUG_RETURN_IN_RESPONSE is ignored in production (force-disabled).")
