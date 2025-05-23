from fastapi import APIRouter
from app.api.v1.router import router as router_v1

router = APIRouter()

# Подключение версионных роутеров
router.include_router(router_v1, prefix="/v1")