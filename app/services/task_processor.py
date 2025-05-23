import logging
import asyncio
import uuid
import json
import time
from typing import Dict, Any, Optional, List

from app.storage.task_store import TaskStore
from app.storage.outbox_store import OutboxStore
from app.ai.anthropic_client import AnthropicClient
from app.core.exceptions import AIException
from app.config import settings

logger = logging.getLogger(__name__)


class TaskProcessor:
    """
    Обработчик задач для асинхронной обработки запросов к Anthropic API
    с поддержкой Batches API и паттерна Transactional Outbox
    """

    def __init__(self, task_store: TaskStore, anthropic_client: AnthropicClient, outbox_store: OutboxStore):
        """
        Инициализация обработчика

        Args:
            task_store: Хранилище задач
            anthropic_client: Клиент Anthropic API
            outbox_store: Хранилище исходящих сообщений (для Transactional Outbox)
        """
        self.task_store = task_store
        self.anthropic_client = anthropic_client
        self.outbox_store = outbox_store
        self.running = False
        self.max_attempts = settings.TASK_MAX_ATTEMPTS
        self.poll_interval = settings.TASK_POLL_INTERVAL  # секунды
        self.batch_check_interval = 60  # 1 минута между проверками пакетов

    async def start(self):
        """
        Запускает обработчик задач
        """
        if self.running:
            return

        self.running = True
        logger.info("Запуск обработчика задач")

        # Запускаем основной цикл обработки
        asyncio.create_task(self._process_loop())

        # Запускаем цикл проверки пакетов
        asyncio.create_task(self._check_batches_loop())

    async def stop(self):
        """
        Останавливает обработчик задач
        """
        logger.info("Остановка обработчика задач")
        self.running = False

    async def _process_loop(self):
        """
        Основной цикл обработки задач
        """
        while self.running:
            try:
                # Получаем список ожидающих задач
                pending_tasks = await self.task_store.get_pending_tasks(limit=10)

                # Обрабатываем каждую задачу
                for task in pending_tasks:
                    # Запускаем обработку в отдельной задаче
                    asyncio.create_task(self._process_task(task))

                # Ожидаем перед следующей проверкой
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.exception(f"Ошибка в основном цикле обработки: {str(e)}")
                await asyncio.sleep(self.poll_interval * 2)

    async def _check_batches_loop(self):
        """
        Цикл проверки статусов пакетов и получения результатов
        """
        while self.running:
            try:
                # Получаем список задач, у которых есть batch_id и статус "processing_by_api"
                task_ids = self.task_store.redis.zrange("tasks:processing_by_api", 0, -1)

                for task_id_bytes in task_ids:
                    task_id = task_id_bytes.decode('utf-8')
                    task = await self.task_store.get_task(task_id)

                    if not task:
                        continue

                    batch_id = task.get("batch_id")
                    if not batch_id:
                        continue

                    # Проверяем статус пакета
                    try:
                        batch_status = await self.anthropic_client.get_batch_status(batch_id)

                        # Если пакет завершил обработку, получаем результаты
                        if batch_status["status"] == "ended":
                            # Получаем все задачи для этого пакета
                            batch_tasks = await self.task_store.get_tasks_by_batch_id(batch_id)

                            # Получаем результаты пакета
                            try:
                                batch_results = await self.anthropic_client.get_batch_results(batch_id)

                                # Обрабатываем результаты для каждой задачи
                                for batch_task in batch_tasks:
                                    document_id = batch_task["document_id"]
                                    task_id = batch_task["task_id"]

                                    if document_id in batch_results:
                                        result_data = batch_results[document_id]

                                        if result_data["status"] == "completed":
                                            # Обновляем статус задачи в ИСХОДНОЙ транзакции
                                            await self.task_store.update_task_status(
                                                task_id=task_id,
                                                status="completed",
                                                data={
                                                    "result": result_data["result"],
                                                    "claude_message_id": result_data.get("message_id", ""),
                                                    "claude_request_id": batch_id
                                                }
                                            )

                                            # Получаем время обработки из результата
                                            processing_time = result_data.get("processing_time", 0)

                                            # TRANSACTIONAL OUTBOX: создаем запись для отправки колбека
                                            message_id = str(uuid.uuid4())
                                            self.outbox_store.create_outbox_message(
                                                message_id=message_id,
                                                task_id=task_id,
                                                document_id=document_id,
                                                status="completed",
                                                payload={
                                                    "result": result_data["result"],
                                                    "processing_time": processing_time,  # Добавляем время обработки
                                                    "input_tokens": result_data.get("input_tokens", 0),
                                                    "output_tokens": result_data.get("output_tokens", 0)
                                                }
                                            )
                                            logger.info(
                                                f"Создано outbox-сообщение {message_id} для задачи {task_id} (время обработки: {processing_time}с)")

                                        else:
                                            # Обновляем статус задачи с ошибкой
                                            await self.task_store.update_task_status(
                                                task_id=task_id,
                                                status="failed",
                                                data={
                                                    "error": result_data.get("error", "Неизвестная ошибка")
                                                }
                                            )

                                            # TRANSACTIONAL OUTBOX: создаем запись для отправки колбека с ошибкой
                                            message_id = str(uuid.uuid4())
                                            self.outbox_store.create_outbox_message(
                                                message_id=message_id,
                                                task_id=task_id,
                                                document_id=document_id,
                                                status="failed",
                                                payload={
                                                    "error": result_data.get("error", "Неизвестная ошибка")
                                                }
                                            )
                                            logger.info(
                                                f"Создано outbox-сообщение {message_id} для задачи {task_id} (ошибка)")

                                    else:
                                        # Если результат не найден, обновляем статус с ошибкой
                                        error_message = f"Результат для документа {document_id} не найден в пакете {batch_id}"
                                        await self.task_store.update_task_status(
                                            task_id=task_id,
                                            status="failed",
                                            data={
                                                "error": error_message
                                            }
                                        )

                                        # TRANSACTIONAL OUTBOX: создаем запись для отправки колбека с ошибкой
                                        message_id = str(uuid.uuid4())
                                        self.outbox_store.create_outbox_message(
                                            message_id=message_id,
                                            task_id=task_id,
                                            document_id=document_id,
                                            status="failed",
                                            payload={
                                                "error": error_message
                                            }
                                        )
                                        logger.info(
                                            f"Создано outbox-сообщение {message_id} для задачи {task_id} (результат не найден)")

                            except Exception as e:
                                logger.exception(f"Ошибка при получении результатов пакета {batch_id}: {str(e)}")
                                # Пропускаем эту итерацию, попробуем снова в следующий раз
                                continue
                    except Exception as e:
                        logger.exception(f"Ошибка при проверке пакета {batch_id}: {str(e)}")

                # Ожидаем перед следующей проверкой
                await asyncio.sleep(self.batch_check_interval)

            except Exception as e:
                logger.exception(f"Ошибка в цикле проверки пакетов: {str(e)}")
                await asyncio.sleep(self.batch_check_interval * 2)

    async def _process_task(self, task: Dict[str, Any]):
        """
        Обрабатывает одну задачу

        Args:
            task: Данные задачи
        """
        task_id = task.get("task_id")
        document_id = task.get("document_id")

        # Проверяем количество попыток
        attempts = int(task.get("attempts", "0"))
        if attempts >= self.max_attempts:
            logger.warning(f"Задача {task_id} превысила максимальное количество попыток ({self.max_attempts})")

            error_message = f"Превышено максимальное количество попыток ({self.max_attempts})"

            # Обновляем статус задачи
            await self.task_store.update_task_status(
                task_id,
                "failed",
                {"error": error_message}
            )

            # TRANSACTIONAL OUTBOX: создаем запись для отправки колбека с ошибкой
            message_id = str(uuid.uuid4())
            self.outbox_store.create_outbox_message(
                message_id=message_id,
                task_id=task_id,
                document_id=document_id,
                status="failed",
                payload={
                    "error": error_message
                }
            )
            logger.info(f"Создано outbox-сообщение {message_id} для задачи {task_id} (макс. попытки)")

            return

        # Увеличиваем счетчик попыток
        new_attempts = await self.task_store.increment_attempt(task_id, "processing")
        if new_attempts is None:
            logger.error(f"Задача {task_id} не найдена при попытке увеличить счетчик попыток")
            return

        # Меняем статус на "processing"
        await self.task_store.update_task_status(task_id, "processing")

        try:
            logger.info(f"Обработка задачи {task_id}, попытка {new_attempts}/{self.max_attempts}")

            # Получаем промпт из задачи
            prompt = task.get("prompt", "")

            # Отправляем запрос к Anthropic Batches API
            result = await self.anthropic_client.create_batch(document_id, prompt)

            # Получаем ID пакета
            batch_id = result["batch_id"]

            # Обновляем статус задачи
            await self.task_store.update_task_status(
                task_id,
                "processing_by_api",  # Новый статус для пакетной обработки
                {
                    "batch_id": batch_id,
                    "claude_request_id": batch_id
                }
            )

            logger.info(f"Задача {task_id} отправлена на обработку в пакете {batch_id}")

        except AIException as e:
            logger.exception(f"AI ошибка при обработке задачи {task_id}: {str(e)}")

            # Проверяем, нужна ли повторная попытка
            retry = getattr(e, 'retry', True)

            # Если не нужна или это последняя попытка, помечаем как failed
            if not retry or new_attempts >= self.max_attempts:
                # Обновляем статус задачи
                await self.task_store.update_task_status(
                    task_id,
                    "failed",
                    {"error": str(e)}
                )

                # TRANSACTIONAL OUTBOX: создаем запись для отправки колбека с ошибкой
                message_id = str(uuid.uuid4())
                self.outbox_store.create_outbox_message(
                    message_id=message_id,
                    task_id=task_id,
                    document_id=document_id,
                    status="failed",
                    payload={
                        "error": str(e)
                    }
                )
                logger.info(f"Создано outbox-сообщение {message_id} для задачи {task_id} (AI ошибка)")

            else:
                # Возвращаем в очередь для повторной попытки
                await self.task_store.update_task_status(task_id, "pending")

        except Exception as e:
            logger.exception(f"Неожиданная ошибка при обработке задачи {task_id}: {str(e)}")

            # Если это последняя попытка, помечаем как failed
            if new_attempts >= self.max_attempts:
                # Обновляем статус задачи
                await self.task_store.update_task_status(
                    task_id,
                    "failed",
                    {"error": str(e)}
                )

                # TRANSACTIONAL OUTBOX: создаем запись для отправки колбека с ошибкой
                message_id = str(uuid.uuid4())
                self.outbox_store.create_outbox_message(
                    message_id=message_id,
                    task_id=task_id,
                    document_id=document_id,
                    status="failed",
                    payload={
                        "error": str(e)
                    }
                )
                logger.info(f"Создано outbox-сообщение {message_id} для задачи {task_id} (неожиданная ошибка)")

            else:
                # Возвращаем в очередь для повторной попытки
                await self.task_store.update_task_status(task_id, "pending")