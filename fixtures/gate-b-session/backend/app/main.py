from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import checkout, profile, receipts

app = FastAPI(title="Orders service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(checkout.router)
app.include_router(profile.router)
app.include_router(receipts.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
