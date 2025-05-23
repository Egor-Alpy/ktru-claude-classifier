import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import verify_api_key
from app.services.ai_service import AIService
from app.schemas.request import ProcessingRequest
from app.schemas.response import ProcessingResponse
from app.core.exceptions import AIException
from app.storage.task_store import TaskStore
from app.ai.anthropic_client import AnthropicClient

router = APIRouter()
logger = logging.getLogger(__name__)


# Получение зависимостей
def get_task_store():
    from app.main import task_store
    return task_store


def get_anthropic_client():
    from app.main import anthropic_client
    return anthropic_client


@router.post(
    "/",
    response_model=ProcessingResponse,
    status_code=status.HTTP_202_ACCEPTED,  # 202 для асинхронной обработки
    dependencies=[Depends(verify_api_key)]
)
async def process_text(
        request: ProcessingRequest,
        ai_service: AIService = Depends(lambda: AIService()),
        task_store: TaskStore = Depends(get_task_store),
        anthropic_client: AnthropicClient = Depends(get_anthropic_client)
):
    """
    Асинхронно обрабатывает текст с помощью AI модели
    """
    try:
        # Генерируем уникальный task_id
        task_id = f"task_{uuid.uuid4()}"
        document_id = request.document_id or f"doc_{uuid.uuid4()}"

        # Получаем шаблон промпта
        prompt = ai_service.get_formatted_prompt(
            text=request.text,
            prompt_template=request.prompt_template
        )

        # Создаем пакет в Anthropic Batches API
        batch_result = await anthropic_client.create_batch(document_id, prompt)
        batch_id = batch_result["batch_id"]

        # Сохраняем задачу в Redis
        await task_store.create_task(
            task_id=task_id,
            document_id=document_id,
            prompt=prompt,
            callback_url=ai_service.get_callback_url(),
            callback_secret=ai_service.get_callback_secret(),
            batch_id=batch_id
        )

        logger.info(f"Создана задача {task_id} для документа {document_id} в пакете {batch_id}")

        # Возвращаем ID задачи и ID пакета
        return ProcessingResponse(
            request_id=task_id,
            batch_id=batch_id,
            result={},
            input_tokens=0,
            output_tokens=0,
            processing_time=0
        )
    except AIException as e:
        logger.exception(f"Ошибка AI при обработке текста: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при обработке текста: {str(e)}"
        )
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при обработке текста: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Неожиданная ошибка: {str(e)}"
        )


@router.get(
    "/{task_id}",
    response_model=ProcessingResponse,
    dependencies=[Depends(verify_api_key)]
)
async def get_task_status(
        task_id: str,
        task_store: TaskStore = Depends(get_task_store),
        anthropic_client: AnthropicClient = Depends(get_anthropic_client)
):
    """
    Получает статус обработки задачи
    """
    try:
        # Получаем задачу из Redis
        task = await task_store.get_task(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Задача {task_id} не найдена"
            )

        # Проверяем наличие batch_id
        batch_id = task.get("batch_id")
        batch_status = None

        # Если есть batch_id, проверяем его статус
        if batch_id:
            try:
                batch_status_info = await anthropic_client.get_batch_status(batch_id)
                batch_status = batch_status_info["status"]
            except Exception as e:
                logger.warning(f"Не удалось получить статус пакета {batch_id}: {str(e)}")

        # Формируем ответ
        response = ProcessingResponse(
            request_id=task_id,
            batch_id=batch_id,
            status=task.get("status", "unknown"),
            batch_status=batch_status,
            result=task.get("result", {}),
            error=task.get("error"),
            input_tokens=0,
            output_tokens=0,
            processing_time=0
        )

        # Если задача завершена, добавляем дополнительную информацию
        if task.get("status") == "completed" and "result" in task:
            # Задача может содержать метаданные о токенах и времени обработки
            # Извлекаем их, если есть
            try:
                result = task.get("result", {})
                if isinstance(result, dict):
                    if "input_tokens" in result:
                        response.input_tokens = result["input_tokens"]
                    if "output_tokens" in result:
                        response.output_tokens = result["output_tokens"]
                    if "processing_time" in result:
                        response.processing_time = result["processing_time"]
            except Exception as e:
                logger.warning(f"Ошибка при извлечении метаданных задачи {task_id}: {str(e)}")

        return response

    except Exception as e:
        logger.exception(f"Ошибка при получении статуса задачи {task_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при получении статуса задачи: {str(e)}"
        )