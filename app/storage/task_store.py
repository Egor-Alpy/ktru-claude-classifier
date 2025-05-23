import json
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

import redis

from app.config import settings
from app.core.exceptions import StorageException


class TaskStore:
    """
    Хранилище задач на базе Redis с поддержкой Batches API
    """

    def __init__(self, redis_url=None):
        """
        Инициализация хранилища

        Args:
            redis_url: URL для подключения к Redis
        """
        redis_url = redis_url or settings.REDIS_URL
        self.redis = redis.from_url(redis_url)

    async def create_task(
            self,
            task_id: str,
            document_id: str,
            prompt: str,
            callback_url: str,
            callback_secret: str,
            batch_id: Optional[str] = None,
            ttl: int = 7 * 24 * 60 * 60
    ) -> Dict[str, Any]:
        """
        Создает новую задачу

        Args:
            task_id: ID задачи
            document_id: ID документа
            prompt: Текст промпта
            callback_url: URL для колбека
            callback_secret: Секрет для подписи колбека
            batch_id: ID пакета Anthropic (для Batches API)
            ttl: Время жизни задачи в секундах (по умолчанию 7 дней)

        Returns:
            Dict[str, Any]: Данные задачи
        """
        now = datetime.utcnow().isoformat()
        task_data = {
            "task_id": task_id,
            "document_id": document_id,
            "status": "pending",
            "prompt": prompt,
            "created_at": now,
            "updated_at": now,
            "callback_url": callback_url,
            "callback_secret": callback_secret,
            "attempts": 0,
            "callback_attempts": 0,
            "claude_message_id": None,
            "claude_request_id": None,
            "batch_id": batch_id,
            "result": None,
            "error": None
        }

        # Сохраняем задачу в Redis
        pipe = self.redis.pipeline()

        # Основные данные задачи
        pipe.hset(f"task:{task_id}", mapping={
            "document_id": document_id,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "attempts": "0",
            "callback_attempts": "0",
            "batch_id": batch_id or ""
        })

        # Большие данные хранятся отдельно
        pipe.set(f"task:{task_id}:prompt", prompt)
        pipe.set(f"task:{task_id}:callback_url", callback_url)
        pipe.set(f"task:{task_id}:callback_secret", callback_secret)

        # Срок жизни
        pipe.expire(f"task:{task_id}", ttl)
        pipe.expire(f"task:{task_id}:prompt", ttl)
        pipe.expire(f"task:{task_id}:callback_url", ttl)
        pipe.expire(f"task:{task_id}:callback_secret", ttl)

        # Индексы для быстрого доступа
        pipe.zadd("tasks:pending", {task_id: time.time()})
        pipe.zadd(f"tasks:document:{document_id}", {task_id: time.time()})

        # Добавляем индекс для пакетов
        if batch_id:
            pipe.zadd(f"tasks:batch:{batch_id}", {task_id: time.time()})

        # Счетчики
        pipe.incr("stats:total_tasks")
        pipe.incr("stats:pending_tasks")

        pipe.execute()

        return task_data

    async def update_task_status(
            self,
            task_id: str,
            status: str,
            data: Optional[Dict[str, Any]] = None,
            ttl: Optional[int] = None
    ) -> bool:
        """
        Обновляет статус задачи

        Args:
            task_id: ID задачи
            status: Новый статус
            data: Дополнительные данные
            ttl: Новое время жизни в секундах

        Returns:
            bool: True, если задача найдена и обновлена
        """
        # Проверяем существование задачи
        exists = self.redis.exists(f"task:{task_id}")
        if not exists:
            return False

        # Получаем предыдущий статус
        prev_status = self.redis.hget(f"task:{task_id}", "status")
        if prev_status is None:
            return False

        prev_status = prev_status.decode('utf-8')

        # Подготавливаем обновления
        pipe = self.redis.pipeline()

        # Обновляем базовые поля
        updates = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }

        if data:
            # Обрабатываем дополнительные данные
            if "claude_message_id" in data:
                updates["claude_message_id"] = data["claude_message_id"]

            if "claude_request_id" in data:
                updates["claude_request_id"] = data["claude_request_id"]

            if "batch_id" in data:
                updates["batch_id"] = data["batch_id"]
                # Обновляем индекс для пакетов
                if data["batch_id"]:
                    pipe.zadd(f"tasks:batch:{data['batch_id']}", {task_id: time.time()})

            if "error" in data:
                pipe.set(f"task:{task_id}:error", data["error"])
                pipe.expire(f"task:{task_id}:error", ttl or 14 * 24 * 60 * 60)

            if "result" in data:
                result_json = json.dumps(data["result"])
                pipe.set(f"task:{task_id}:result", result_json)
                pipe.expire(f"task:{task_id}:result", ttl or 3 * 24 * 60 * 60)

        # Обновляем поля задачи
        pipe.hset(f"task:{task_id}", mapping=updates)

        # Обновляем TTL, если указан
        if ttl:
            pipe.expire(f"task:{task_id}", ttl)
            pipe.expire(f"task:{task_id}:prompt", ttl)
            pipe.expire(f"task:{task_id}:callback_url", ttl)
            pipe.expire(f"task:{task_id}:callback_secret", ttl)

        # Обновляем индексы
        if prev_status != status:
            # Удаляем из старого индекса
            pipe.zrem(f"tasks:{prev_status}", task_id)

            # Добавляем в новый индекс
            pipe.zadd(f"tasks:{status}", {task_id: time.time()})

            # Обновляем счетчики
            if prev_status == "pending":
                pipe.decr("stats:pending_tasks")

            if status == "completed":
                pipe.incr("stats:completed_tasks")
            elif status == "failed":
                pipe.incr("stats:failed_tasks")

        pipe.execute()
        return True

    async def get_task(self, task_id: str, include_prompt: bool = False) -> Optional[Dict[str, Any]]:
        """
        Получает данные задачи

        Args:
            task_id: ID задачи
            include_prompt: Включать ли промпт в результат

        Returns:
            Optional[Dict[str, Any]]: Данные задачи или None, если задача не найдена
        """
        if not self.redis.exists(f"task:{task_id}"):
            return None

        # Получаем основные данные задачи
        task_data = self.redis.hgetall(f"task:{task_id}")
        if not task_data:
            return None

        # Преобразуем байты в строки
        task = {k.decode('utf-8'): v.decode('utf-8') for k, v in task_data.items()}

        # Добавляем ID задачи
        task["task_id"] = task_id

        # Получаем промпт, если требуется
        if include_prompt and self.redis.exists(f"task:{task_id}:prompt"):
            prompt = self.redis.get(f"task:{task_id}:prompt")
            if prompt:
                task["prompt"] = prompt.decode('utf-8')

        # Получаем URL колбека
        if self.redis.exists(f"task:{task_id}:callback_url"):
            callback_url = self.redis.get(f"task:{task_id}:callback_url")
            if callback_url:
                task["callback_url"] = callback_url.decode('utf-8')

        # Получаем секрет для колбека
        if self.redis.exists(f"task:{task_id}:callback_secret"):
            callback_secret = self.redis.get(f"task:{task_id}:callback_secret")
            if callback_secret:
                task["callback_secret"] = callback_secret.decode('utf-8')

        # Получаем результат, если есть
        if self.redis.exists(f"task:{task_id}:result"):
            result_json = self.redis.get(f"task:{task_id}:result")
            if result_json:
                try:
                    task["result"] = json.loads(result_json.decode('utf-8'))
                except json.JSONDecodeError:
                    task["result"] = result_json.decode('utf-8')

        # Получаем ошибку, если есть
        if self.redis.exists(f"task:{task_id}:error"):
            error = self.redis.get(f"task:{task_id}:error")
            if error:
                task["error"] = error.decode('utf-8')

        return task

    async def get_tasks_by_batch_id(self, batch_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Получение списка задач по ID пакета

        Args:
            batch_id: ID пакета
            limit: Максимальное количество задач

        Returns:
            List[Dict[str, Any]]: Список задач
        """
        # Получаем ID задач из отсортированного множества по ID пакета
        task_ids = self.redis.zrange(f"tasks:batch:{batch_id}", 0, limit - 1)

        result = []
        for task_id in task_ids:
            task_id = task_id.decode('utf-8')
            task = await self.get_task(task_id)
            if task:
                result.append(task)

        return result

    async def get_pending_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получение списка ожидающих задач

        Args:
            limit: Максимальное количество задач

        Returns:
            List[Dict[str, Any]]: Список задач
        """
        # Получаем ID задач со статусом "pending" из отсортированного множества
        task_ids = self.redis.zrange("tasks:pending", 0, limit - 1)

        result = []
        for task_id in task_ids:
            task_id = task_id.decode('utf-8')
            task = await self.get_task(task_id, include_prompt=True)
            if task:
                result.append(task)

        return result

    async def increment_attempt(self, task_id: str, type_: str = "processing") -> Optional[int]:
        """
        Увеличивает счетчик попыток задачи

        Args:
            task_id: ID задачи
            type_: Тип попытки ('processing' или 'callback')

        Returns:
            Optional[int]: Новое значение счетчика или None, если задача не найдена
        """
        # Проверяем существование задачи
        if not self.redis.exists(f"task:{task_id}"):
            return None

        # Определяем поле для счетчика
        field = "attempts" if type_ == "processing" else "callback_attempts"

        # Увеличиваем счетчик
        new_count = self.redis.hincrby(f"task:{task_id}", field, 1)

        return new_count