import json
import time
from datetime import datetime
from typing import Dict, Any, Optional, List


class OutboxStore:
    """
    Хранилище исходящих сообщений (колбеков) для реализации паттерна Transactional Outbox.
    Использует Redis для хранения данных и обеспечения гарантированной доставки сообщений.
    """

    def __init__(self, redis_client):
        """
        Инициализация хранилища

        Args:
            redis_client: Клиент Redis
        """
        self.redis = redis_client

        # TTL для разных типов сообщений (в секундах)
        self.pending_ttl = 7 * 24 * 60 * 60  # 7 дней для ожидающих отправки
        self.processed_ttl = 3 * 24 * 60 * 60  # 3 дня для успешно отправленных
        self.failed_ttl = 14 * 24 * 60 * 60  # 14 дней для неудачных попыток

    def _prepare_redis_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Подготавливает данные для сохранения в Redis, заменяя несовместимые типы

        Args:
            data: Исходные данные

        Returns:
            Dict[str, Any]: Подготовленные данные для Redis
        """
        result = {}
        for k, v in data.items():
            if v is None:
                result[k] = ""
            elif isinstance(v, dict):
                result[k] = json.dumps(v)
            else:
                result[k] = v
        return result

    def create_outbox_message(
            self,
            message_id: str,
            task_id: str,
            document_id: str,
            status: str,
            payload: Dict[str, Any]
    ) -> bool:
        """
        Создает новое исходящее сообщение в outbox

        Args:
            message_id: Уникальный ID сообщения
            task_id: ID задачи
            document_id: ID документа
            status: Статус обработки (completed/failed)
            payload: Полезная нагрузка (результат/ошибка)

        Returns:
            bool: True, если сообщение создано успешно
        """
        now = time.time()
        message_data = {
            "message_id": message_id,
            "task_id": task_id,
            "document_id": document_id,
            "status": status,
            "payload": json.dumps(payload),
            "created_at": now,
            "sent_at": None,  # Будет автоматически преобразовано в ""
            "retry_count": 0,
            "next_retry_at": now,
            "last_error": None  # Будет автоматически преобразовано в ""
        }

        # Подготавливаем данные для Redis
        redis_data = self._prepare_redis_data(message_data)

        # Сохраняем данные в Redis с использованием pipe для атомарности
        pipe = self.redis.pipeline()

        # 1. Сохраняем данные сообщения
        pipe.hset(f"outbox:message:{message_id}", mapping=redis_data)

        # 2. Добавляем в очередь ожидающих сообщений, сортированную по времени следующей попытки
        pipe.zadd("outbox:pending", {message_id: now})

        # 3. Индексы для доступа по task_id и document_id
        pipe.sadd(f"outbox:task:{task_id}", message_id)
        pipe.sadd(f"outbox:document:{document_id}", message_id)

        # 4. Устанавливаем TTL
        pipe.expire(f"outbox:message:{message_id}", self.pending_ttl)
        pipe.expire(f"outbox:task:{task_id}", self.pending_ttl)
        pipe.expire(f"outbox:document:{document_id}", self.pending_ttl)

        # Выполняем все команды атомарно
        pipe.execute()

        return True

    def mark_as_sent(self, message_id: str) -> bool:
        """
        Отмечает сообщение как успешно отправленное

        Args:
            message_id: ID сообщения

        Returns:
            bool: True, если сообщение найдено и обновлено
        """
        # Проверяем существование сообщения
        exists = self.redis.exists(f"outbox:message:{message_id}")
        if not exists:
            return False

        now = time.time()

        # Обновляем статус сообщения
        pipe = self.redis.pipeline()

        # 1. Обновляем данные сообщения
        pipe.hset(f"outbox:message:{message_id}", "sent_at", now)

        # 2. Удаляем из очереди ожидающих
        pipe.zrem("outbox:pending", message_id)

        # 3. Добавляем в список успешно отправленных
        pipe.zadd("outbox:sent", {message_id: now})

        # 4. Обновляем TTL
        pipe.expire(f"outbox:message:{message_id}", self.processed_ttl)

        # Получаем task_id и document_id для обновления индексов
        task_id = self.redis.hget(f"outbox:message:{message_id}", "task_id")
        document_id = self.redis.hget(f"outbox:message:{message_id}", "document_id")

        if task_id:
            task_id = task_id.decode('utf-8')
            pipe.expire(f"outbox:task:{task_id}", self.processed_ttl)

        if document_id:
            document_id = document_id.decode('utf-8')
            pipe.expire(f"outbox:document:{document_id}", self.processed_ttl)

        # Выполняем все команды атомарно
        pipe.execute()

        return True

    def mark_as_failed(self, message_id: str, error: str, retry_delay_seconds: int = 60) -> bool:
        """
        Отмечает сообщение как неудачно отправленное и планирует повторную попытку

        Args:
            message_id: ID сообщения
            error: Текст ошибки
            retry_delay_seconds: Задержка перед следующей попыткой в секундах

        Returns:
            bool: True, если сообщение найдено и обновлено
        """
        # Проверяем существование сообщения
        exists = self.redis.exists(f"outbox:message:{message_id}")
        if not exists:
            return False

        # Получаем текущее количество попыток
        retry_count_bytes = self.redis.hget(f"outbox:message:{message_id}", "retry_count")
        retry_count = int(retry_count_bytes.decode('utf-8')) if retry_count_bytes else 0

        # Вычисляем экспоненциальную задержку для следующей попытки
        # Формула: base_delay * (2 ^ retry_count) с максимальным значением
        next_retry_delay = min(retry_delay_seconds * (2 ** retry_count), 24 * 60 * 60)  # Максимум 1 день
        next_retry_at = time.time() + next_retry_delay

        # Обновляем статус сообщения
        pipe = self.redis.pipeline()

        # 1. Обновляем данные сообщения
        update_data = {
            "retry_count": retry_count + 1,
            "next_retry_at": next_retry_at,
            "last_error": error
        }

        # Подготавливаем данные для Redis
        redis_data = self._prepare_redis_data(update_data)

        pipe.hset(f"outbox:message:{message_id}", mapping=redis_data)

        # 2. Обновляем позицию в очереди ожидающих
        pipe.zadd("outbox:pending", {message_id: next_retry_at})

        # 3. Обновляем TTL
        pipe.expire(f"outbox:message:{message_id}", self.failed_ttl)

        # Получаем task_id и document_id для обновления индексов
        task_id = self.redis.hget(f"outbox:message:{message_id}", "task_id")
        document_id = self.redis.hget(f"outbox:message:{message_id}", "document_id")

        if task_id:
            task_id = task_id.decode('utf-8')
            pipe.expire(f"outbox:task:{task_id}", self.failed_ttl)

        if document_id:
            document_id = document_id.decode('utf-8')
            pipe.expire(f"outbox:document:{document_id}", self.failed_ttl)

        # Выполняем все команды атомарно
        pipe.execute()

        return True

    def get_pending_messages(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получает список сообщений, ожидающих отправки

        Args:
            limit: Максимальное количество сообщений

        Returns:
            List[Dict[str, Any]]: Список сообщений
        """
        now = time.time()

        # Получаем ID сообщений, готовых к отправке (next_retry_at <= now)
        message_ids = self.redis.zrangebyscore("outbox:pending", 0, now, start=0, num=limit)

        result = []
        for message_id_bytes in message_ids:
            message_id = message_id_bytes.decode('utf-8')

            # Получаем данные сообщения
            message_data = self.redis.hgetall(f"outbox:message:{message_id}")

            if not message_data:
                # Если данные не найдены, удаляем из очереди
                self.redis.zrem("outbox:pending", message_id)
                continue

            # Преобразуем байты в строки
            message = {k.decode('utf-8'): v.decode('utf-8') for k, v in message_data.items()}

            # Преобразуем payload из JSON
            try:
                message['payload'] = json.loads(message.get('payload', '{}'))
            except json.JSONDecodeError:
                message['payload'] = {}

            # Преобразуем числовые поля
            for field in ['created_at', 'sent_at', 'retry_count', 'next_retry_at']:
                if field in message and message[field] not in [None, 'None', '']:
                    message[field] = float(message[field]) if field in ['created_at', 'sent_at',
                                                                        'next_retry_at'] else int(message[field])

            result.append(message)

        return result

    def get_message_by_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает данные сообщения по ID

        Args:
            message_id: ID сообщения

        Returns:
            Optional[Dict[str, Any]]: Данные сообщения или None, если не найдено
        """
        # Получаем данные сообщения
        message_data = self.redis.hgetall(f"outbox:message:{message_id}")

        if not message_data:
            return None

        # Преобразуем байты в строки
        message = {k.decode('utf-8'): v.decode('utf-8') for k, v in message_data.items()}

        # Преобразуем payload из JSON
        try:
            message['payload'] = json.loads(message.get('payload', '{}'))
        except json.JSONDecodeError:
            message['payload'] = {}

        # Преобразуем числовые поля
        for field in ['created_at', 'sent_at', 'retry_count', 'next_retry_at']:
            if field in message and message[field] not in [None, 'None', '']:
                message[field] = float(message[field]) if field in ['created_at', 'sent_at', 'next_retry_at'] else int(
                    message[field])

        return message

    def get_messages_by_task_id(self, task_id: str, include_sent: bool = False) -> List[Dict[str, Any]]:
        """
        Получает список сообщений по ID задачи

        Args:
            task_id: ID задачи
            include_sent: Включать ли успешно отправленные сообщения

        Returns:
            List[Dict[str, Any]]: Список сообщений
        """
        # Получаем ID сообщений для задачи
        message_ids_bytes = self.redis.smembers(f"outbox:task:{task_id}")

        if not message_ids_bytes:
            return []

        result = []
        for message_id_bytes in message_ids_bytes:
            message_id = message_id_bytes.decode('utf-8')

            # Проверяем статус сообщения
            if not include_sent:
                in_pending = self.redis.zscore("outbox:pending", message_id)
                if not in_pending:
                    continue

            # Получаем данные сообщения
            message = self.get_message_by_id(message_id)
            if message:
                result.append(message)

        return result