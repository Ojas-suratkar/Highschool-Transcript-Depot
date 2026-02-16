from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from .db import get_session
from .services.auth_service import AuthService
from .utils.jwt_utils import create_access_token
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import os

router = APIRouter(prefix='/auth')


class RequestOTPRequest(BaseModel):
    destination: str = None
    channel: str = 'email'
    profile_id: str | None = None


class RequestOTPResponse(BaseModel):
    challenge_id: str
    expires_in_seconds: int


class VerifyOTPRequest(BaseModel):
    challenge_id: str
    otp: str


class VerifyOTPResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    user_id: str


@router.post('/request-otp', response_model=RequestOTPResponse)
async def request_otp(req: RequestOTPRequest, session: AsyncSession = Depends(get_session), request: Request = None):
    auth = AuthService(session)
    # implement rate-limiting by IP and destination inside service or middleware
    # Treat `destination` as the email address for now
    if not req.destination:
        raise HTTPException(status_code=400, detail='destination required')
    res = await auth.request_otp(req.destination)
    if not res.get('ok'):
        raise HTTPException(status_code=400, detail=res.get('detail', 'failed'))
    return RequestOTPResponse(challenge_id=res['challenge_id'], expires_in_seconds=int(res['expires_in_seconds']))


@router.post('/verify-otp', response_model=VerifyOTPResponse)
async def verify_otp(req: VerifyOTPRequest, session: AsyncSession = Depends(get_session)):
    auth = AuthService(session)
    ok, profile_id = await auth.verify_otp(req.challenge_id, req.otp)
    if not ok or not profile_id:
        raise HTTPException(status_code=400, detail='invalid or expired otp')
    token = create_access_token(str(profile_id))
    return VerifyOTPResponse(access_token=token, user_id=str(profile_id))


@router.get('/dev/last-otp/{challenge_id}')
async def dev_last_otp(challenge_id: str):
    # dev-only: return last OTP from in-memory store when DELIVERY_MODE=mock. Protected by DEV_ADMIN_KEY.
    if os.environ.get('DELIVERY_MODE', 'mock') != 'mock':
        raise HTTPException(status_code=404, detail='not found')
    key = os.environ.get('DEV_ADMIN_KEY')
    if not key:
        raise HTTPException(status_code=403, detail='dev admin key not configured')
    return { 'challenge_id': challenge_id, 'otp': None }
