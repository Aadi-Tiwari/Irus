from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    email: str
    amount: int


class CheckoutResponse(BaseModel):
    order_id: str
    status: str
