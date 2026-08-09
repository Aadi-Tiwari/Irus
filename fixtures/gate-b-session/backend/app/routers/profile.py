from fastapi import APIRouter

from ..deps import CurrentCustomerId
from ..schemas import ProfileResponse, ProfileUpdateRequest
from ..store import get_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.put("", response_model=ProfileResponse)
def update_profile(payload: ProfileUpdateRequest, customer_id: CurrentCustomerId) -> ProfileResponse:
    profile = get_profile(customer_id)
    profile.display_name = payload.display_name
    profile.marketing_emails = payload.marketing_emails
    return ProfileResponse(
        customer_id=profile.customer_id,
        display_name=profile.display_name,
        marketing_emails=profile.marketing_emails,
    )
