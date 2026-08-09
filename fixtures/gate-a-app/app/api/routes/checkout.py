from fastapi import APIRouter

from app.models import CheckoutRequest, CheckoutResponse

router = APIRouter()


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(payload: CheckoutRequest) -> CheckoutResponse:
    return CheckoutResponse(order_id="ord_1", status="ok")
