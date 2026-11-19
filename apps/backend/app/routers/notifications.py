from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.services.notification_service import ensure_table

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(60, le=200),
):
    ensure_table()
    rows = (
        await session.execute(
            text(
                "SELECT id, created_at, level, category, title, message, read, meta "
                "FROM app_notifications ORDER BY created_at DESC LIMIT :l"
            ),
            {"l": limit},
        )
    ).mappings().all()
    unread = (
        await session.execute(
            text("SELECT COUNT(*) FROM app_notifications WHERE read = false")
        )
    ).scalar() or 0
    return {"notifications": [dict(r) for r in rows], "unread": int(unread)}


@router.get("/unread-count")
async def unread_count(session: AsyncSession = Depends(get_session)):
    ensure_table()
    n = (
        await session.execute(
            text("SELECT COUNT(*) FROM app_notifications WHERE read = false")
        )
    ).scalar() or 0
    return {"unread": int(n)}


@router.post("/mark-read")
async def mark_read(payload: dict, session: AsyncSession = Depends(get_session)):
    ensure_table()
    ids = payload.get("ids") or []
    ids = [int(i) for i in ids if str(i).isdigit()]
    if ids:
        await session.execute(
            text("UPDATE app_notifications SET read = true WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
        await session.commit()
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_read(session: AsyncSession = Depends(get_session)):
    ensure_table()
    await session.execute(text("UPDATE app_notifications SET read = true WHERE read = false"))
    await session.commit()
    return {"ok": True}


@router.post("/clear")
async def clear_read(session: AsyncSession = Depends(get_session)):
    """Remove already-read notifications (keeps unread)."""
    ensure_table()
    await session.execute(text("DELETE FROM app_notifications WHERE read = true"))
    await session.commit()
    return {"ok": True}
