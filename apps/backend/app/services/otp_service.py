"""
Legacy OTPService shim.

The project now uses `services/auth_service.py` and `services/email_sender.py`.
This file is kept as a shim to avoid breaking imports; any attempt to instantiate
OTPService will raise a RuntimeError and point devs to the new implementation.
"""

class OTPService:
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "OTPService (legacy) was removed. Use services.auth_service.AuthService instead.")
