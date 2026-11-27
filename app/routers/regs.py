"""Regulations metadata: the seeds' as-of date + computed staleness.

No DB, no network — a cheap, deterministic endpoint backing the
"Regs as of <date>" stamp and the >12-month staleness banner in the
regs/plan UI (and the offline-cached copies of it).
"""
from fastapi import APIRouter

from ..services import regs_meta

router = APIRouter(prefix="/api/regs", tags=["regs"])


@router.get("/meta")
def meta():
    """The regs seeds' as-of date + staleness verdict (banner driver)."""
    return regs_meta.regs_stamp()
