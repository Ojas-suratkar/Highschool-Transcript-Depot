from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..services.auth_service import AuthService
from ..utils.jwt_utils import create_access_token, decode_token
from typing import Optional

router = APIRouter(prefix='/auth', tags=['auth'])


class SignupRequest(BaseModel):
    email: EmailStr
    phone: str
    password: str
    first_name: str
    last_name: str
    institution_name: str
    city: Optional[str] = None
    zip: Optional[str] = None
    role: str


class SignupResponse(BaseModel):
    challenge_id: Optional[str] = None
    expires_in_seconds: int


class RequestOTPRequest(BaseModel):
    email: EmailStr
    password: Optional[str] = None


class RequestOTPResponse(BaseModel):
    challenge_id: Optional[str]
    expires_in_seconds: int


class VerifyOTPRequest(BaseModel):
    challenge_id: str
    otp: str


class VerifyOTPResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    user_id: str


@router.post('/signup', response_model=SignupResponse)
async def signup(req: SignupRequest, session: AsyncSession = Depends(get_session)):
    svc = AuthService(session)
    result = await svc.signup(
        req.email,
        req.phone,
        req.password,
        req.first_name,
        req.last_name,
        req.institution_name,
        req.city,
        req.zip,
        req.role,
    )
    # If signup reports the email is already registered, send an OTP via
    # the request_otp flow instead so callers can verify the existing account.
    if not result.get('ok', False) and result.get('detail') == 'already_registered':
        result = await svc.request_otp(req.email)

    # For any remaining error, return a 400 so the frontend can display it.
    if not result.get('ok', False):
        detail = result.get('detail', 'Failed to signup')
        raise HTTPException(status_code=400, detail=detail)

    challenge_id = result.get('challenge_id')
    if not challenge_id:
        # Unexpected: service reported ok but no challenge id
        raise HTTPException(status_code=500, detail='signup_flow_failed')

    return SignupResponse(challenge_id=challenge_id, expires_in_seconds=result.get('expires_in_seconds', 0))


@router.post('/request-otp', response_model=RequestOTPResponse)
async def request_otp(req: RequestOTPRequest, session: AsyncSession = Depends(get_session)):
    svc = AuthService(session)
    # if password was provided, validate credentials and generate OTP
    if req.password:
        result = await svc.login_and_request_otp(req.email, req.password)
    else:
        result = await svc.request_otp(req.email)
    if not result.get('ok', False):
        detail = result.get('detail', 'Failed to request OTP')
        raise HTTPException(status_code=400, detail=detail)

    return RequestOTPResponse(challenge_id=result.get('challenge_id'), expires_in_seconds=result.get('expires_in_seconds', 600))


@router.post('/verify-otp', response_model=VerifyOTPResponse)
async def verify_otp(req: VerifyOTPRequest, session: AsyncSession = Depends(get_session)):
    svc = AuthService(session)
    ok, user_id = await svc.verify_otp(req.challenge_id, req.otp)
    if not ok:
        raise HTTPException(status_code=400, detail='invalid_or_expired')
    # user_id is a primitive string (no ORM instance) returned from the service
    token = create_access_token(str(user_id))
    return VerifyOTPResponse(access_token=token, user_id=str(user_id))


def get_current_user(token: str = Depends(lambda: None)):
    # placeholder: integrate OAuth/JWT dependency properly
    raise HTTPException(status_code=401, detail='not implemented')


@router.get('/me')
async def me():
    raise HTTPException(status_code=501, detail='not implemented')
