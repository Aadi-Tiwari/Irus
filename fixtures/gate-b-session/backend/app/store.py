"""In-memory persistence. Swap for a real database without touching the routers."""

import uuid
from dataclasses import dataclass, field


@dataclass
class Order:
    id: str
    email: str
    amount_cents: int
    status: str


@dataclass
class Profile:
    customer_id: str
    display_name: str = ""
    marketing_emails: bool = False


@dataclass
class Receipt:
    id: str
    order_id: str
    filename: str
    content_type: str
    content: bytes = field(repr=False)


orders: dict[str, Order] = {}
profiles: dict[str, Profile] = {}
receipts: dict[str, Receipt] = {}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def create_order(email: str, amount_cents: int) -> Order:
    order = Order(id=new_id("ord"), email=email, amount_cents=amount_cents, status="pending")
    orders[order.id] = order
    return order


def get_profile(customer_id: str) -> Profile:
    return profiles.setdefault(customer_id, Profile(customer_id=customer_id))


def save_receipt(order_id: str, filename: str, content_type: str, content: bytes) -> Receipt:
    receipt = Receipt(
        id=new_id("rcpt"),
        order_id=order_id,
        filename=filename,
        content_type=content_type,
        content=content,
    )
    receipts[receipt.id] = receipt
    return receipt
