from pydantic import BaseModel
from typing import Optional


class SendOTPRequest(BaseModel):
    # Either provide `contact` (email or phone) OR `profile_id` to look up the contact
    contact: Optional[str] = None
    profile_id: Optional[str] = None
    via: Optional[str] = 'email'  # 'email' or 'sms' - if omitted we'll pick available contact
    metadata: Optional[dict] = None


class SendOTPResponse(BaseModel):
    success: bool
    detail: str
    debug_otp: Optional[str] = None


class VerifyOTPVerifyRequest(BaseModel):
    contact: str
    via: str
    otp: str


class VerifyOTPResponse(BaseModel):
    success: bool
    profile_id: str
