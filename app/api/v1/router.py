from fastapi import APIRouter
from app.api.v1.endpoints.processing import router as processing_router
from app.api.v1.endpoints.products import router as products_router

router = APIRouter()

# Подключение маршрутов
router.include_router(processing_router, prefix="/processing", tags=["processing"])
router.include_router(products_router, prefix="/products", tags=["products"])