from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

app = FastAPI()
router = APIRouter(prefix="/api")


class CheckoutRequest(BaseModel):
    email: str
    amount: int
    note: str | None = None


class CheckoutResponse(BaseModel):
    order_id: str
    status: str


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(payload: CheckoutRequest):
    return {"order_id": "ord_1", "status": "ok"}


@router.get("/orders/{order_id}")
async def get_order(order_id: str):
    return {"order_id": order_id}


@router.post("/admin/purge")
async def purge():
    return {"purged": True}


@router.get("/health")
async def health():
    return {"ok": True}


app.include_router(router)
