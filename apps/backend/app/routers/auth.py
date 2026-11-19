from fastapi import APIRouter, Depends, HTTPException, Header, Cookie, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..db import get_session
from ..models import Profile, Institution
from ..services.auth_service import AuthService
from ..utils.jwt_utils import create_access_token, decode_token, JWT_EXP_SECONDS
from typing import Optional
import uuid
import os

router = APIRouter(prefix="/auth")


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
    debug_otp: Optional[str] = None


class RequestOTPRequest(BaseModel):
    email: EmailStr
    password: Optional[str] = None


class RequestOTPResponse(BaseModel):
    challenge_id: Optional[str]
    expires_in_seconds: int
    debug_otp: Optional[str] = None


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

    return SignupResponse(
        challenge_id=challenge_id,
        expires_in_seconds=result.get('expires_in_seconds', 0),
        debug_otp=result.get('debug_otp'),
    )


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

    return RequestOTPResponse(
        challenge_id=result.get('challenge_id'),
        expires_in_seconds=result.get('expires_in_seconds', 600),
        debug_otp=result.get('debug_otp'),
    )


@router.post('/verify-otp', response_model=VerifyOTPResponse)
async def verify_otp(req: VerifyOTPRequest, response: Response, session: AsyncSession = Depends(get_session)):
    svc = AuthService(session)
    ok, user_id = await svc.verify_otp(req.challenge_id, req.otp)
    if not ok:
        raise HTTPException(status_code=400, detail='invalid_or_expired')
    # user_id is a primitive string (no ORM instance) returned from the service
    token = create_access_token(str(user_id))
    # also set HttpOnly cookie so browser clients that don't attach Authorization
    # headers can still authenticate using the cookie.
    resp = VerifyOTPResponse(access_token=token, user_id=str(user_id))
    # set cookie with same expiration as token
    try:
        max_age = int(JWT_EXP_SECONDS)
    except Exception:
        max_age = None
    response.set_cookie(
        key='access_token',
        value=token,
        httponly=True,
        secure=False,
        max_age=max_age,
        samesite='lax',
    )
    return resp


# ================================
# JWT Authentication Dependency
# ================================

async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_access_token: Optional[str] = Header(None, alias='X-Access-Token'),
    access_token_cookie: Optional[str] = Cookie(None, alias='access_token'),
    session: AsyncSession = Depends(get_session)
) -> Profile:
    """
    Extract and validate JWT token from Authorization header.
    Returns the authenticated user's Profile.
    """
    # Support multiple token delivery mechanisms so clients that use a cookie
    # or a custom header (X-Access-Token) still work without changing UI.
    token_source = None
    if authorization:
        token_source = authorization
    elif x_access_token:
        token_source = x_access_token
    elif access_token_cookie:
        token_source = access_token_cookie

    if not token_source:
        raise HTTPException(status_code=401, detail='Authorization header missing')

    # If token was passed as a full header value (e.g. "Bearer <token>"),
    # extract the token; otherwise assume the raw token string was provided.
    parts = token_source.split()
    if len(parts) == 1:
        token = parts[0]
    elif len(parts) == 2 and parts[0].lower() == 'bearer':
        token = parts[1]
    else:
        raise HTTPException(status_code=401, detail='Invalid authorization header format')
    
    try:
        payload = decode_token(token)
        user_id_str = payload.get('sub')
        if not user_id_str:
            raise HTTPException(status_code=401, detail='Invalid token: missing subject')
    except Exception as e:
        raise HTTPException(status_code=401, detail=f'Invalid or expired token: {str(e)}')
    
    # Parse UUID
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail='Invalid user ID in token')
    
    # Fetch user from database
    result = await session.execute(select(Profile).where(Profile.id == user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=401, detail='User not found')
    
    return user


# ================================
# User Profile Response Schema
# ================================

class InstitutionResponse(BaseModel):
    id: int
    institution_name: str
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None

    class Config:
        from_attributes = True


class UserProfileResponse(BaseModel):
    id: str
    email: str
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    institution_id: Optional[int] = None
    institution: Optional[InstitutionResponse] = None
    is_verified: bool

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None


async def _serialize_user(current_user: Profile, session: AsyncSession) -> UserProfileResponse:
    """Build the profile response, including the linked institution if any."""
    institution_data = None
    if current_user.institution_id:
        result = await session.execute(
            select(Institution).where(Institution.id == current_user.institution_id)
        )
        institution = result.scalars().first()
        if institution:
            institution_data = InstitutionResponse(
                id=institution.id,
                institution_name=institution.institution_name,
                city=institution.city,
                state=institution.state,
                zip_code=institution.zip_code,
            )

    return UserProfileResponse(
        id=str(current_user.id),
        email=current_user.email,
        phone=current_user.phone,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        role=current_user.role,
        institution_id=current_user.institution_id,
        institution=institution_data,
        is_verified=current_user.is_verified,
    )


@router.get('/me', response_model=UserProfileResponse)
async def me(
    current_user: Profile = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get the current authenticated user's profile.
    Returns user_id, institution_id, and other profile details.
    """
    return await _serialize_user(current_user, session)


@router.patch('/me', response_model=UserProfileResponse)
async def update_me(
    payload: UpdateProfileRequest,
    current_user: Profile = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Update the current user's editable profile fields (name, phone, role) and
    persist them so the change survives a refresh / re-login.
    """
    data = payload.model_dump(exclude_unset=True)
    for field in ('first_name', 'last_name', 'phone', 'role'):
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip() or None
            setattr(current_user, field, value)

    await session.commit()
    await session.refresh(current_user)
    return await _serialize_user(current_user, session)




# (dev-token endpoint removed) Development-only auth helpers were deleted to
# enforce that all clients use the standard OTP / verify-otp flow and real
# authenticated sessions for actions. If you need a local shortcut in the
# future, add a temporary script in your dev environment instead of an
# application endpoint.
