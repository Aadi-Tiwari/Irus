from pydantic import BaseModel, EmailStr, Field


class CheckoutRequest(BaseModel):
    email: EmailStr
    amount_cents: int = Field(gt=0)


class CheckoutResponse(BaseModel):
    order_id: str
    status: str


class ProfileUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    marketing_emails: bool


class ProfileResponse(BaseModel):
    customer_id: str
    display_name: str
    marketing_emails: bool


class ReceiptResponse(BaseModel):
    file_id: str
    order_id: str
    filename: str
    content_type: str
    size_bytes: int
