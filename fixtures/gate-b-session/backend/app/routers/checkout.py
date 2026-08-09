from fastapi import APIRouter, status

from ..schemas import CheckoutRequest, CheckoutResponse
from ..store import create_order

router = APIRouter(prefix="/orders", tags=["checkout"])


@router.post("", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
def checkout(payload: CheckoutRequest) -> CheckoutResponse:
    order = create_order(email=payload.email, amount_cents=payload.amount_cents)
    return CheckoutResponse(order_id=order.id, status=order.status)
