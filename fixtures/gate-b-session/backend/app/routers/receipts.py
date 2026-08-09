from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from ..schemas import ReceiptResponse
from ..store import orders, save_receipt

router = APIRouter(prefix="/orders", tags=["receipts"])

MAX_BYTES = 10 * 1024 * 1024


@router.post(
    "/{order_id}/receipt",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_receipt(order_id: str, file: Annotated[UploadFile, File()]) -> ReceiptResponse:
    if order_id not in orders:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Receipt must be an image",
        )

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Receipt is larger than 10 MB",
        )

    receipt = save_receipt(
        order_id=order_id,
        filename=file.filename or "receipt",
        content_type=content_type,
        content=content,
    )
    return ReceiptResponse(
        file_id=receipt.id,
        order_id=receipt.order_id,
        filename=receipt.filename,
        content_type=receipt.content_type,
        size_bytes=len(content),
    )
