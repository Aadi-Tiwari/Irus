"""Producer side, as agent A would have written it working alone."""

import os

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api")

STRIPE_KEY = os.getenv("STRIPE_KEY")


class CheckoutRequest(BaseModel):
    email: str
    amount: int
    note: str = ""


class RefundRequest(BaseModel):
    order_id: str
    reason: str


@router.post("/checkout")
async def checkout(payload: CheckoutRequest):
    return {"ok": True, "charged": payload.amount}


@router.post("/refund")
async def refund(payload: RefundRequest):
    return {"ok": True}


@router.get("/health")
async def health():
    return {"status": "up"}
