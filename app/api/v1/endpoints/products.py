import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Dict, Any, Optional

from app.core.security import verify_api_key
from app.schemas.product import ProductBatchRequest, ProductBatchResponse, ProductBatchStatusResponse
from app.services.product_processor import ProductProcessor

router = APIRouter()
logger = logging.getLogger(__name__)


# Получение зависимостей
def get_product_processor():
    from app.main import product_processor
    return product_processor


@router.post(
    "/batch",
    response_model=ProductBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)]
)
async def process_product_batch(
        request: ProductBatchRequest,
        product_processor: ProductProcessor = Depends(get_product_processor)
):
    """
    Создает новый батч для обработки товаров и определения кодов КТРУ
    """
    try:
        # Проверяем наличие товаров
        if not request.products:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Список товаров не может быть пустым"
            )

        # Ограничиваем размер батча
        max_batch_size = 100
        if len(request.products) > max_batch_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Слишком много товаров в батче. Максимальный размер: {max_batch_size}"
            )

        # Запускаем обработку батча
        batch_id = await product_processor.process_product_batch(request.products)

        # Возвращаем информацию о созданном батче
        return ProductBatchResponse(
            batch_id=batch_id,
            status="pending",
            product_count=len(request.products),
            processed_count=0
        )

    except Exception as e:
        logger.exception(f"Ошибка при создании батча товаров: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при создании батча товаров: {str(e)}"
        )


@router.get(
    "/batch/{batch_id}",
    response_model=ProductBatchStatusResponse,
    dependencies=[Depends(verify_api_key)]
)
async def get_batch_status(
        batch_id: str,
        include_products: bool = Query(False, description="Включать ли информацию о товарах в ответ"),
        product_processor: ProductProcessor = Depends(get_product_processor)
):
    """
    Получает статус обработки батча товаров
    """
    try:
        # Получаем статус батча
        batch_status = await product_processor.get_batch_status(batch_id, include_products)

        # Если батч не найден, возвращаем 404
        if batch_status["status"] == "not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Батч {batch_id} не найден"
            )

        # Возвращаем статус
        return ProductBatchStatusResponse(**batch_status)

    except HTTPException:
        raise  # Пробрасываем HTTPException дальше

    except Exception as e:
        logger.exception(f"Ошибка при получении статуса батча {batch_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при получении статуса батча: {str(e)}"
        )