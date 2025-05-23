import logging
import json
import time
import re
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime

from anthropic import AsyncAnthropic

from app.config import settings
from app.core.exceptions import AIException

logger = logging.getLogger(__name__)


class AnthropicClient:
    """
    Асинхронный клиент для работы с Anthropic API с поддержкой Batches API
    """

    def __init__(self):
        """
        Инициализация клиента
        """
        self.api_key = settings.ANTHROPIC_API_KEY
        self.model = settings.ANTHROPIC_MODEL
        self.max_tokens = settings.ANTHROPIC_MAX_TOKENS
        self.client = AsyncAnthropic(api_key=self.api_key)

    async def create_batch(self, document_id: str, prompt: str) -> Dict[str, Any]:
        """
        Создание пакетного запроса к Anthropic API

        Args:
            document_id: ID документа
            prompt: Текст промпта

        Returns:
            Dict[str, Any]: Результат создания пакета

        Raises:
            AIException: При ошибке создания пакета
        """
        start_time = time.time()

        try:
            # Создаем пакет с одним запросом с поддержкой веб-поиска
            batch = await self.client.beta.messages.batches.create(
                requests=[
                    {
                        "custom_id": document_id,  # Используем document_id как идентификатор запроса
                        "params": {
                            "model": self.model,
                            "max_tokens": self.max_tokens,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": prompt
                                }
                            ],
                            "temperature": 0.0,
                            "tools": [
                                {
                                    "name": "web_search",
                                    "description": "Search the web for information about products and KTRU codes"
                                }
                            ],
                            "tool_choice": "auto"
                        }
                    }
                ]
            )

            # Формируем результат
            processing_time = time.time() - start_time

            return {
                "batch_id": batch.id,
                "document_id": document_id,
                "status": batch.processing_status,
                "created_at": batch.created_at,
                "expires_at": batch.expires_at,
                "request_counts": batch.request_counts,
                "processing_time": processing_time
            }

        except Exception as e:
            logger.exception(f"Ошибка при создании пакета: {str(e)}")

            # Определяем, нужно ли делать повторную попытку
            retry = self._should_retry_error(str(e))
            raise AIException(f"Ошибка при создании пакета: {str(e)}", retry=retry)

    async def get_batch_status(self, batch_id: str) -> Dict[str, Any]:
        """
        Получение статуса пакета

        Args:
            batch_id: ID пакета

        Returns:
            Dict[str, Any]: Статус пакета

        Raises:
            AIException: При ошибке получения статуса
        """
        try:
            # Получаем информацию о пакете
            batch = await self.client.beta.messages.batches.retrieve(batch_id)

            # Вычисляем время обработки, если пакет завершил обработку
            processing_time = None
            if batch.ended_at and batch.created_at:
                try:
                    created_time = datetime.fromisoformat(batch.created_at.replace('Z', '+00:00'))
                    ended_time = datetime.fromisoformat(batch.ended_at.replace('Z', '+00:00'))
                    processing_time = (ended_time - created_time).total_seconds()
                    logger.info(f"Вычислено время обработки пакета {batch_id}: {processing_time} секунд")
                except Exception as e:
                    logger.warning(f"Не удалось вычислить время обработки пакета {batch_id}: {str(e)}")

            return {
                "batch_id": batch.id,
                "status": batch.processing_status,
                "created_at": batch.created_at,
                "ended_at": batch.ended_at,
                "expires_at": batch.expires_at,
                "request_counts": batch.request_counts,
                "results_url": batch.results_url,
                "processing_time": processing_time  # Добавляем вычисленное время обработки
            }

        except Exception as e:
            logger.exception(f"Ошибка при получении статуса пакета {batch_id}: {str(e)}")
            raise AIException(f"Ошибка при получении статуса пакета: {str(e)}")

    async def get_batch_results(self, batch_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Получение результатов обработки пакета

        Args:
            batch_id: ID пакета

        Returns:
            Dict[str, Dict[str, Any]]: Результаты обработки

        Raises:
            AIException: При ошибке получения результатов
        """
        try:
            # Сначала получаем информацию о пакете для проверки статуса
            batch = await self.client.beta.messages.batches.retrieve(batch_id)

            # Если обработка не завершена, возвращаем ошибку
            if batch.processing_status != "ended":
                raise AIException(
                    f"Пакет {batch_id} еще не завершил обработку. Текущий статус: {batch.processing_status}",
                    retry=True
                )

            # Если нет URL для результатов, возвращаем ошибку
            if not batch.results_url:
                raise AIException(f"У пакета {batch_id} отсутствует URL для получения результатов")

            # Вычисляем время обработки
            processing_time = None
            if batch.ended_at and batch.created_at:
                try:
                    created_time = datetime.fromisoformat(batch.created_at.replace('Z', '+00:00'))
                    ended_time = datetime.fromisoformat(batch.ended_at.replace('Z', '+00:00'))
                    processing_time = (ended_time - created_time).total_seconds()
                    logger.info(f"Вычислено время обработки пакета {batch_id}: {processing_time} секунд")
                except Exception as e:
                    logger.warning(f"Не удалось вычислить время обработки пакета {batch_id}: {str(e)}")

            # Получаем результаты
            result_stream = await self.client.beta.messages.batches.results(batch_id)
            results = {}

            # Обрабатываем каждый ответ в потоке результатов
            async for entry in result_stream:
                custom_id = entry.custom_id

                if entry.result.type == "succeeded":
                    # Извлекаем текст ответа
                    response_text = ""
                    for content_item in entry.result.message.content:
                        if content_item.type == "text":
                            response_text = content_item.text
                            break

                    # Извлекаем JSON из ответа
                    extracted_json = self._extract_json_from_response(response_text)

                    # Добавляем информацию об использовании токенов и времени обработки
                    results[custom_id] = {
                        "status": "completed",
                        "result": extracted_json,
                        "message_id": entry.result.message.id,
                        "input_tokens": entry.result.message.usage.input_tokens,
                        "output_tokens": entry.result.message.usage.output_tokens,
                        "processing_time": processing_time,  # Добавляем вычисленное время обработки
                        "content": response_text
                    }
                elif entry.result.type == "errored":
                    # Обрабатываем ошибку
                    results[custom_id] = {
                        "status": "failed",
                        "error": entry.result.error.message if hasattr(entry.result.error, 'message') else str(
                            entry.result.error)
                    }
                else:
                    # Для других статусов
                    results[custom_id] = {
                        "status": entry.result.type
                    }

            return results

        except Exception as e:
            logger.exception(f"Ошибка при получении результатов пакета {batch_id}: {str(e)}")

            # Определяем, нужно ли делать повторную попытку
            retry = self._should_retry_error(str(e))
            raise AIException(f"Ошибка при получении результатов: {str(e)}", retry=retry)

    def _should_retry_error(self, error_message: str) -> bool:
        """
        Определяет, нужно ли делать повторную попытку для данной ошибки

        Args:
            error_message: Текст ошибки

        Returns:
            bool: True если нужно повторить попытку, False в противном случае
        """
        # Повторяем попытки для временных проблем
        if any(keyword in error_message.lower() for keyword in [
            "timeout",
            "connection",
            "network",
            "rate limit",
            "too many requests",
            "429",
            "overloaded",
            "529"
        ]):
            return True

        # НЕ повторяем для проблем с содержимым или форматом
        if any(keyword in error_message.lower() for keyword in [
            "invalid",
            "content policy",
            "malformed",
            "400",
            "format",
            "invalid_request_error"
        ]):
            return False

        # По умолчанию повторяем попытку
        return True

    def _extract_json_from_response(self, response_text: str) -> Dict[str, Any]:
        """
        Извлечение JSON из текстового ответа

        Args:
            response_text: Текст ответа

        Returns:
            Dict[str, Any]: Данные JSON

        Raises:
            AIException: Если не удалось извлечь JSON
        """
        # Для нашей задачи определения КТРУ - ответ не в формате JSON, а простая строка с кодом КТРУ
        # Просто возвращаем ответ как есть, без обработки
        return response_text.strip()