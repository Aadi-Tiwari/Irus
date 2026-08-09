"""The same application with both sides agreeing. Zero findings expected."""

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class CheckoutRequest(BaseModel):
    email: str
    amount: int
    note: str = ""


@router.post("/checkout")
async def checkout(payload: CheckoutRequest):
    return {"ok": True, "charged": payload.amount}


@router.get("/health")
async def health():
    return {"status": "up"}


# Without this the router is declared and never mounted, which is a real
# finding and made this "clean" fixture report two of them. A fixture whose
# docstring promises zero findings has to actually mount its own routes.
app = FastAPI()
app.include_router(router)
