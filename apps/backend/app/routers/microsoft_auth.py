import json
import time
import hmac
import hashlib
import base64
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import get_session
from ..models import Profile, Institution
from ..utils.jwt_utils import create_access_token
from ..core.config import settings

router = APIRouter(prefix="/auth/microsoft")

MICROSOFT_AUTHORITY = "https://login.microsoftonline.com"
GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"
SCOPES = "openid email profile User.Read"
ALLOWED_DOMAIN = "csulb.edu"


def _create_state() -> str:
    nonce = secrets.token_urlsafe(16)
    payload = json.dumps({"n": nonce, "t": int(time.time())})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def _verify_state(state: str, max_age: int = 600) -> bool:
    try:
        payload_b64, sig = state.rsplit(".", 1)
        expected = hmac.new(
            settings.JWT_SECRET.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        padding = 4 - len(payload_b64) % 4
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * padding).decode())
        return int(time.time()) - payload["t"] <= max_age
    except Exception:
        return False


@router.get("/login")
async def microsoft_login():
    frontend_url = settings.FRONTEND_ORIGIN or "http://localhost:5173"
    if not settings.MICROSOFT_CLIENT_ID:
        return RedirectResponse(f"{frontend_url}/login?error=sso_not_configured")

    tenant = settings.MICROSOFT_TENANT_ID or "organizations"
    state = _create_state()
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "prompt": "select_account",
    }
    auth_url = f"{MICROSOFT_AUTHORITY}/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/callback")
async def microsoft_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    frontend_url = settings.FRONTEND_ORIGIN or "http://localhost:5173"
    callback_base = f"{frontend_url}/sso/callback"

    if error:
        return RedirectResponse(f"{callback_base}?error={error}")

    if not code or not state or not _verify_state(state):
        return RedirectResponse(f"{callback_base}?error=invalid_state")

    tenant = settings.MICROSOFT_TENANT_ID or "organizations"
    token_url = f"{MICROSOFT_AUTHORITY}/{tenant}/oauth2/v2.0/token"

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            token_url,
            data={
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse(f"{callback_base}?error=token_exchange_failed")

        token_data = token_resp.json()
        ms_access_token = token_data.get("access_token")
        if not ms_access_token:
            return RedirectResponse(f"{callback_base}?error=no_access_token")

        graph_resp = await client.get(
            GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {ms_access_token}"},
            params={
                "$select": "id,displayName,givenName,surname,mail,userPrincipalName,jobTitle,department"
            },
        )
        if graph_resp.status_code != 200:
            return RedirectResponse(f"{callback_base}?error=graph_failed")

        ms_profile = graph_resp.json()

    microsoft_oid: str | None = ms_profile.get("id")
    email = (ms_profile.get("mail") or ms_profile.get("userPrincipalName") or "").lower().strip()

    if not email or not email.endswith(f"@{ALLOWED_DOMAIN}"):
        return RedirectResponse(f"{callback_base}?error=domain_not_allowed")

    first_name = (ms_profile.get("givenName") or "").strip()
    last_name = (ms_profile.get("surname") or "").strip()
    display_name = (ms_profile.get("displayName") or "").strip()
    job_title = (ms_profile.get("jobTitle") or "").strip()

    if not first_name and display_name:
        parts = display_name.split()
        first_name = parts[0] if parts else ""
        last_name = parts[-1] if len(parts) > 1 else last_name

    # Resolve user: by OID first, then fall back to email
    user: Profile | None = None
    if microsoft_oid:
        result = await session.execute(
            select(Profile).where(Profile.microsoft_oid == microsoft_oid)
        )
        user = result.scalars().first()

    if user is None:
        result = await session.execute(select(Profile).where(Profile.email == email))
        user = result.scalars().first()
        if user and microsoft_oid:
            user.microsoft_oid = microsoft_oid

    if user is None:
        # Auto-create CSULB institution if it doesn't exist yet
        inst_result = await session.execute(
            select(Institution).where(
                Institution.institution_name.ilike("California State University, Long Beach")
            )
        )
        institution = inst_result.scalars().first()
        if institution is None:
            institution = Institution(
                institution_name="California State University, Long Beach",
                city="Long Beach",
                state="CA",
                zip_code="90840",
            )
            session.add(institution)
            await session.flush()

        user = Profile(
            id=uuid.uuid4(),
            email=email,
            first_name=first_name or None,
            last_name=last_name or None,
            microsoft_oid=microsoft_oid,
            role=job_title or "staff",
            institution_id=institution.id,
            is_verified=True,
            verified_at=datetime.now(timezone.utc),
        )
        session.add(user)
    else:
        # Keep profile in sync with Microsoft's directory
        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        if microsoft_oid:
            user.microsoft_oid = microsoft_oid
        if not user.is_verified:
            user.is_verified = True
            user.verified_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)

    await session.commit()

    jwt_token = create_access_token(str(user.id))
    return RedirectResponse(f"{callback_base}?token={jwt_token}")
