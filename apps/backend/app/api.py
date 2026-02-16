"""
Legacy API router removed — authentication is now provided by `routers/auth.py`.
This stub file exists so that any accidental imports don't break; please remove references
to this module and delete the file when ready.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get('/deprecated')
async def deprecated():
    return {"detail": "deprecated - use /auth/* endpoints"}
