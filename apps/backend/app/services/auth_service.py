import secrets
import datetime
import uuid
from typing import Tuple, Optional, Union

from passlib.context import CryptContext # type: ignore
from sqlalchemy import select, update, func # type: ignore
from sqlalchemy.ext.asyncio import AsyncSession # type: ignore
from sqlalchemy.exc import IntegrityError # type: ignore

from ..models import Profile, OTPChallenge
from .email_sender import MockEmailSender, SMTPEmailSender, MailerSendSender
from ..core.config import settings

# Use pbkdf2_sha256 to avoid native bcrypt builds in some environments
pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class AuthService:
    """
    Service responsible for signup, OTP generation and verification.

    Fixes included:
    - OTP normalization (handles leading zeros like "012345")
    - challenge_id casting (UUID/int tolerant)
    - verify_otp supports BOTH:
        * signup OTPChallenge-based verification
        * existing Profile otp_* fields verification (request_otp/login_and_request_otp)
    - resend cooldown enforcement
    - safer transaction handling (rollback on IntegrityError)
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.otp_ttl = int(settings.OTP_TTL_SECONDS)
        self.resend_cooldown = int(settings.OTP_RESEND_COOLDOWN_SECONDS)
        self.max_attempts = int(settings.OTP_MAX_ATTEMPTS)

        dm = getattr(settings, "DELIVERY_MODE", "").lower()
        if dm == "mock" or (
            not getattr(settings, "MAILERSEND_API_KEY", None)
            and not getattr(settings, "SMTP_HOST", None)
        ):
            self.sender = MockEmailSender()
        elif dm == "mailersend" or getattr(settings, "MAILERSEND_API_KEY", None):
            self.sender = MailerSendSender()
        elif dm == "smtp" or getattr(settings, "SMTP_HOST", None):
            self.sender = SMTPEmailSender()
        else:
            self.sender = MockEmailSender()

    # ---------------------------
    # Helpers
    # ---------------------------

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def _make_code(self) -> str:
        # Always 6 digits, may start with 0
        return f"{secrets.randbelow(1_000_000):06d}"

    def _normalize_otp(self, otp: str) -> str:
        """
        Important: Many clients strip leading zeros if OTP is handled as a number.
        This ensures "12345" becomes "012345" for 6-digit codes.
        """
        otp = (otp or "").strip()
        if otp.isdigit() and len(otp) < 6:
            otp = otp.zfill(6)
        return otp

    def _cast_id(self, raw: str) -> Union[uuid.UUID, int, str]:
        """
        Tries to cast challenge_id/user_id into a UUID or int when possible.
        Falls back to string for DBs that store IDs as strings.
        """
        raw = (raw or "").strip()
        if not raw:
            return raw
        # int? (prefer integers because many tables use BIGINT ids)
        try:
            return int(raw)
        except Exception:
            pass
        # UUID?
        try:
            return uuid.UUID(raw)
        except Exception:
            pass
        return raw

    def _ensure_aware_utc(self, dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)

    def _cooldown_ok(self, last_sent_at: Optional[datetime.datetime], now: datetime.datetime) -> bool:
        if not last_sent_at:
            return True
        last_sent_at = self._ensure_aware_utc(last_sent_at)
        return (now - last_sent_at).total_seconds() >= float(self.resend_cooldown or 0)

    async def _send_code_email(self, email: str, code: str, subject: str) -> None:
        # Keep consistent body and always mention TTL in minutes
        ttl_min = max(1, self.otp_ttl // 60)
        body = (
            f"<p>Your verification code is <strong>{code}</strong>."
            f" It expires in {ttl_min} minute(s).</p>"
        )
        await self.sender.send(email, subject, body)

    # ---------------------------
    # Public API
    # ---------------------------

    async def signup(
        self,
        email: str,
        phone: str,
        password: str,
        first_name: str,
        last_name: str,
        institution_name: str,
        city: Optional[str],
        zip: Optional[str],
        role: str,
    ) -> dict:
    # NOTE: removed early 'already_registered' check so dev/testing can resend
    # OTPs and re-run signup flows even when a Profile already exists.
    # The verify flow still ensures we don't create duplicates at commit time.

        now = self._now()

        # Optional: prevent multiple active signup challenges per email
        q_ch = select(OTPChallenge).where(func.lower(OTPChallenge.email) == email.lower())
        res_ch = await self.session.execute(q_ch)
        old_ch = res_ch.scalars().first()
        if old_ch:
            # Enforce resend cooldown
            if not self._cooldown_ok(getattr(old_ch, "last_sent_at", None), now):
                return {"ok": False, "detail": "cooldown"}

            # Refresh OTP on existing challenge (instead of creating duplicates)
            code = self._make_code()
            otp_hash = pwd_ctx.hash(code)
            expires = now + datetime.timedelta(seconds=self.otp_ttl)

            old_ch.phone = phone
            old_ch.password_hash = pwd_ctx.hash(password)
            old_ch.first_name = first_name
            old_ch.last_name = last_name
            old_ch.institution_name = institution_name
            old_ch.city = city
            old_ch.zip = zip
            old_ch.role = role
            old_ch.otp_hash = otp_hash
            old_ch.expires_at = expires
            old_ch.attempts = 0
            old_ch.last_sent_at = now

            await self.session.commit()

            # Send email (if this fails, user can retry; we keep OTP stored)
            try:
                await self._send_code_email(email, code, subject="Verify your email")
            except Exception:
                pass

            return {"ok": True, "challenge_id": str(old_ch.id), "expires_in_seconds": self.otp_ttl}

        # New challenge
        code = self._make_code()
        otp_hash = pwd_ctx.hash(code)
        expires = now + datetime.timedelta(seconds=self.otp_ttl)

        ch = OTPChallenge(
            email=email,
            phone=phone,
            password_hash=pwd_ctx.hash(password),
            first_name=first_name,
            last_name=last_name,
            institution_name=institution_name,
            city=city,
            zip=zip,
            role=role,
            otp_hash=otp_hash,
            expires_at=expires,
            attempts=0,
            last_sent_at=now,
        )
        self.session.add(ch)
        await self.session.commit()

        try:
            await self._send_code_email(email, code, subject="Verify your email")
        except Exception:
            # non-fatal for signup flow; user can retry
            pass

        return {"ok": True, "challenge_id": str(ch.id), "expires_in_seconds": self.otp_ttl}

    async def request_otp(self, email: str) -> dict:
        q = select(Profile).where(func.lower(Profile.email) == email.lower())
        res = await self.session.execute(q)
        user = res.scalars().first()
        if not user:
            return {"ok": False, "detail": "not_found"}

        now = self._now()

        # Enforce resend cooldown
        if not self._cooldown_ok(getattr(user, "otp_last_sent_at", None), now):
            return {"ok": False, "detail": "cooldown"}

        code = self._make_code()
        otp_hash = pwd_ctx.hash(code)
        expires = now + datetime.timedelta(seconds=self.otp_ttl)

        await self.session.execute(
            update(Profile)
            .where(Profile.id == user.id)
            .values(
                otp_hash=otp_hash,
                otp_expires_at=expires,
                otp_attempts=0,
                otp_last_sent_at=now,
            )
        )
        await self.session.commit()

        try:
            await self._send_code_email(user.email, code, subject="Your verification code")
        except Exception:
            pass

        # IMPORTANT: This "challenge_id" is actually the Profile id in this flow.
        return {"ok": True, "challenge_id": str(user.id), "expires_in_seconds": self.otp_ttl}

    async def login_and_request_otp(self, email: str, password: str) -> dict:
        q = select(Profile).where(func.lower(Profile.email) == email.lower())
        res = await self.session.execute(q)
        user = res.scalars().first()
        if not user:
            return {"ok": False, "detail": "invalid_credentials"}
        if not pwd_ctx.verify(password, user.password_hash):
            return {"ok": False, "detail": "invalid_credentials"}

        now = self._now()

        if not self._cooldown_ok(getattr(user, "otp_last_sent_at", None), now):
            return {"ok": False, "detail": "cooldown"}

        code = self._make_code()
        otp_hash = pwd_ctx.hash(code)
        expires = now + datetime.timedelta(seconds=self.otp_ttl)

        await self.session.execute(
            update(Profile)
            .where(Profile.id == user.id)
            .values(
                otp_hash=otp_hash,
                otp_expires_at=expires,
                otp_attempts=0,
                otp_last_sent_at=now,
            )
        )
        await self.session.commit()

        try:
            await self._send_code_email(user.email, code, subject="Your verification code")
        except Exception:
            pass

        return {"ok": True, "challenge_id": str(user.id), "expires_in_seconds": self.otp_ttl}

    async def verify_otp(self, challenge_id: str, otp: str) -> Tuple[bool, Optional[str]]:
        """
        Verifies OTP for either:
        - Signup flow: OTPChallenge.id == challenge_id, creates Profile, deletes OTPChallenge
        - Login/request flow: Profile.id == challenge_id, verifies against profile otp_hash and clears otp fields
        """
        otp_norm = self._normalize_otp(otp)
        cid = self._cast_id(challenge_id)
        now = self._now()

        # 1) Try signup flow first: OTPChallenge
        q_ch = select(OTPChallenge).where(OTPChallenge.id == cid)
        res_ch = await self.session.execute(q_ch)
        ch = res_ch.scalars().first()
        # copy challenge attributes into locals immediately to avoid any
        # potential lazy-loading / expired-attribute access later which
        # can trigger greenlet_spawn errors if the session state changes.
        if ch:
            ch_email = ch.email
            ch_phone = ch.phone
            ch_first_name = ch.first_name
            ch_last_name = ch.last_name
            ch_institution_name = getattr(ch, 'institution_name', None)
            ch_city = getattr(ch, 'city', None)
            ch_zip = getattr(ch, 'zip', None)
            ch_role = ch.role
            ch_password_hash = ch.password_hash
        else:
            ch_email = ch_phone = ch_first_name = ch_last_name = ch_institution_name = ch_city = ch_zip = ch_role = ch_password_hash = None
        if ch:
            expires_at = self._ensure_aware_utc(getattr(ch, "expires_at", None))
            if expires_at is not None and expires_at < now:
                return False, None

            if (getattr(ch, "attempts", 0) or 0) >= (self.max_attempts or 0):
                return False, None

            if not pwd_ctx.verify(otp_norm, ch.otp_hash):
                ch.attempts = (getattr(ch, "attempts", 0) or 0) + 1
                await self.session.commit()
                return False, None

            # Before creating, ensure profile doesn't already exist for this email
            q_existing = select(Profile).where(func.lower(Profile.email) == ch_email.lower())
            res_existing = await self.session.execute(q_existing)
            existing = res_existing.scalars().first()
            if existing:
                # Cleanup challenge (optional but recommended)
                await self.session.delete(ch)
                await self.session.commit()
                # return primitive id to avoid ORM attribute access outside session
                return True, str(existing.id)
            # Find or create institution using ORM
            institution_id = None
            if ch_institution_name:
                from ..models import Institution  # local import to avoid cycles

                # Try to find existing institution (case-insensitive name; exact city/zip)
                q_inst = select(Institution).where(
                    func.lower(Institution.institution_name) == func.lower(ch_institution_name or ''),
                    func.coalesce(Institution.city, '') == func.coalesce(ch_city or '' , ''),
                    func.coalesce(Institution.zip_code, '') == func.coalesce(ch_zip or '' , ''),
                )
                res_inst = await self.session.execute(q_inst)
                inst = res_inst.scalars().first()
                if inst:
                    institution_id = inst.id
                else:
                    new_inst = Institution(institution_name=ch_institution_name or '', city=ch_city or '', zip_code=ch_zip or '')
                    self.session.add(new_inst)
                    # flush to get id
                    try:
                        await self.session.flush()
                    except IntegrityError:
                        await self.session.rollback()
                        # try to fetch again in case of race
                        res_inst2 = await self.session.execute(q_inst)
                        inst2 = res_inst2.scalars().first()
                        if inst2:
                            institution_id = inst2.id
                        else:
                            institution_id = None
                    else:
                        institution_id = new_inst.id

                profile = Profile(
                email=ch_email,
                phone=ch_phone or "",
                first_name=ch_first_name,
                last_name=ch_last_name,
                institution_id=institution_id,
                role=ch_role,
                password_hash=ch_password_hash,
                is_verified=True,
                verified_at=now,
            )
            self.session.add(profile)
            await self.session.delete(ch)

            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                # Race / constraint issue; best effort: fetch and return existing
                res_existing2 = await self.session.execute(
                    select(Profile).where(func.lower(Profile.email) == profile.email.lower())
                )
                prof2 = res_existing2.scalars().first()
                # return primitive id to avoid ORM attribute access outside session
                return (prof2 is not None), (str(prof2.id) if prof2 else None)
            return True, str(profile.id)

        # 2) If not a challenge, try Profile-based OTP verification (login/request flow)
        q_p = select(Profile).where(Profile.id == cid)
        res_p = await self.session.execute(q_p)
        user = res_p.scalars().first()
        if not user:
            return False, None

        expires_at = self._ensure_aware_utc(getattr(user, "otp_expires_at", None))
        if not getattr(user, "otp_hash", None):
            return False, None
        if expires_at is not None and expires_at < now:
            return False, None

        if (getattr(user, "otp_attempts", 0) or 0) >= (self.max_attempts or 0):
            return False, None

        if not pwd_ctx.verify(otp_norm, user.otp_hash):
            await self.session.execute(
                update(Profile)
                .where(Profile.id == user.id)
                .values(otp_attempts=(getattr(user, "otp_attempts", 0) or 0) + 1)
            )
            await self.session.commit()
            return False, None

        # Success: clear OTP fields so the code can't be reused
        await self.session.execute(
            update(Profile)
            .where(Profile.id == user.id)
            .values(
                otp_hash=None,
                otp_expires_at=None,
                otp_attempts=0,
                is_verified=True,
                verified_at=now,
                # keep otp_last_sent_at for cooldown tracking
            )
        )
        await self.session.commit()
        # return primitive id to avoid ORM attribute access outside session
        return True, str(user.id)
