from fastapi import APIRouter

from app.api.routes import checkout, health

api_router = APIRouter()
api_router.include_router(checkout.router)
api_router.include_router(health.router)
