import logging
import asyncio
import hmac
import hashlib
import json
import time
import random
import aiohttp
from typing import Dict, Any, Optional, Tuple

from app.storage.outbox_store import OutboxStore
from app.config import settings

logger = logging.getLogger(__name__)


class OutboxRelayService:
    """
    Сервис-релей для отправки сообщений из хранилища исходящих сообщений (outbox)
    в соответствии с паттерном Transactional Outbox.
    """

    def __init__(self, outbox_store: OutboxStore):
        """
        Инициализация сервиса-релея

        Args:
            outbox_store: Хранилище исходящих сообщений
        """
        self.outbox_store = outbox_store
        self.running = False
        self.poll_interval = 5  # секунды между проверками
        self.batch_size = 10  # количество сообщений за одну итерацию
        self.relay_task = None

    async def start(self):
        """
        Запускает сервис-релей
        """
        if self.running:
            return

        self.running = True
        logger.info("Запуск сервиса-релея для исходящих сообщений")

        # Запускаем основной цикл обработки
        self.relay_task = asyncio.create_task(self._relay_loop())

    async def stop(self):
        """
        Останавливает сервис-релей
        """
        logger.info("Остановка сервиса-релея для исходящих сообщений")
        self.running = False

        if self.relay_task:
            self.relay_task.cancel()
            try:
                await self.relay_task
            except asyncio.CancelledError:
                pass

    async def _relay_loop(self):
        """
        Основной цикл отправки сообщений из outbox
        """
        while self.running:
            try:
                # Получаем список сообщений для отправки
                pending_messages = self.outbox_store.get_pending_messages(limit=self.batch_size)

                if pending_messages:
                    logger.info(f"Найдено {len(pending_messages)} сообщений для отправки")

                    # Обрабатываем каждое сообщение
                    for message in pending_messages:
                        # Запускаем обработку в отдельной задаче, чтобы не блокировать цикл
                        asyncio.create_task(self._process_message(message))

                # Ожидаем перед следующей проверкой
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.exception(f"Ошибка в основном цикле релея: {str(e)}")
                await asyncio.sleep(self.poll_interval * 2)  # Увеличиваем задержку при ошибке

    async def _process_message(self, message: Dict[str, Any]):
        """
        Обрабатывает одно сообщение из outbox

        Args:
            message: Данные сообщения
        """
        message_id = message.get("message_id")
        task_id = message.get("task_id")
        document_id = message.get("document_id")
        status = message.get("status")
        payload = message.get("payload", {})

        logger.info(f"Обработка сообщения {message_id} для документа {document_id}")

        try:
            # Отправляем колбек
            success, error = await self._send_callback(
                task_id=task_id,
                document_id=document_id,
                status=status,
                payload=payload,
                callback_url=message.get("callback_url")
            )

            if success:
                # Отмечаем сообщение как успешно отправленное
                self.outbox_store.mark_as_sent(message_id)
                logger.info(f"Сообщение {message_id} успешно отправлено")
            else:
                # Отмечаем сообщение как неудачно отправленное
                self.outbox_store.mark_as_failed(message_id, error or "Неизвестная ошибка")
                logger.warning(f"Ошибка при отправке сообщения {message_id}: {error}")

        except Exception as e:
            logger.exception(f"Неожиданная ошибка при обработке сообщения {message_id}: {str(e)}")
            self.outbox_store.mark_as_failed(message_id, str(e))

    async def _send_callback(
            self,
            task_id: str,
            document_id: str,
            status: str,
            payload: Dict[str, Any],
            callback_url: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Отправляет колбек в Document Service

        Args:
            task_id: ID задачи
            document_id: ID документа
            status: Статус обработки
            payload: Данные для отправки
            callback_url: URL для отправки колбека

        Returns:
            tuple: (успех, ошибка)
        """
        if not callback_url:
            callback_url = settings.CALLBACK_URL

        # Получаем секрет для подписи
        callback_secret = settings.CALLBACK_SECRET

        # Формируем данные колбека
        callback_data = {
            "task_id": task_id,
            "document_id": document_id,
            "status": status
        }

        # Добавляем результат или ошибку в зависимости от статуса
        if status == "completed":
            # Добавляем ключевые данные результата
            if "result" in payload:
                callback_data["result"] = payload["result"]

            # Добавляем время обработки напрямую в корень объекта
            if "processing_time" in payload:
                callback_data["processing_time"] = payload["processing_time"]

            # Добавляем другие дополнительные поля, если они есть
            for field in ["input_tokens", "output_tokens"]:
                if field in payload:
                    callback_data[field] = payload[field]
        elif status == "failed":
            callback_data["error"] = payload.get("error", "Неизвестная ошибка")

        try:
            # Сериализуем данные в JSON
            payload_bytes = json.dumps(callback_data).encode('utf-8')

            # Создаем подпись
            signature = hmac.new(
                callback_secret.encode('utf-8'),
                payload_bytes,
                hashlib.sha256
            ).hexdigest()

            # Заголовки запроса
            headers = {
                "Content-Type": "application/json",
                "X-Signature": signature
            }

            # Добавляем джиттер к таймауту для предотвращения синхронизированных повторных попыток
            jitter = random.uniform(0.8, 1.2)
            timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT * jitter)

            # Отправляем запрос
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(callback_url, data=payload_bytes, headers=headers) as response:
                    if response.status >= 200 and response.status < 300:
                        # Успешная отправка
                        return True, None
                    else:
                        # Ошибка отправки
                        error_text = await response.text()
                        return False, f"HTTP ошибка {response.status}: {error_text}"

        except aiohttp.ClientError as e:
            return False, f"Ошибка соединения: {str(e)}"
        except Exception as e:
            return False, f"Неожиданная ошибка: {str(e)}"