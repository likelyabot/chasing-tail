"""Gear: Angler's tackle (static knowledge, served read-only)."""
from fastapi import APIRouter

from ..knowledge import GEAR

router = APIRouter(prefix="/api/gear", tags=["gear"])


@router.get("")
def get_gear():
    return GEAR
