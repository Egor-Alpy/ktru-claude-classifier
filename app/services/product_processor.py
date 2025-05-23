import logging
import asyncio
import uuid
import json
import time
import re
from typing import Dict, Any, List, Optional

from app.ai.anthropic_client import AnthropicClient
from app.storage.task_store import TaskStore
from app.storage.outbox_store import OutboxStore
from app.services.search_service import SearchService
from app.core.exceptions import AIException
from app.config import settings

logger = logging.getLogger(__name__)


class ProductProcessor:
    """
    Обработчик товаров для определения кодов КТРУ с использованием Anthropic API
    """

    def __init__(self, task_store: TaskStore, anthropic_client: AnthropicClient, outbox_store: OutboxStore):
        """
        Инициализация обработчика

        Args:
            task_store: Хранилище задач
            anthropic_client: Клиент Anthropic API
            outbox_store: Хранилище исходящих сообщений
        """
        self.task_store = task_store
        self.anthropic_client = anthropic_client
        self.outbox_store = outbox_store
        self.search_service = SearchService()
        self.ktru_prompt_template = """Я предоставлю тебе JSON-файл с описанием товара. Твоя задача - определить единственный точный код КТРУ (Каталог товаров, работ, услуг) для этого товара. Если ты не можешь определить код с высокой уверенностью (более 95%), ответь только "код не найден".

ВАЖНО: ВСЕГДА ИСПОЛЬЗУЙ ВЕБ-ПОИСК для нахождения точного кода КТРУ. Следуй этим шагам:
1. Изучи всю информацию из JSON: title, description, category, attributes, brand
2. Выполни поиск в интернете для нахождения соответствующего кода КТРУ/ОКПД2
3. Поисковые запросы должны включать "КТРУ код", "ОКПД2 код", наименование товара, его категорию и характеристики
4. Обрати особое внимание на результаты с сайтов zakupki.gov.ru, zakupki.kontur.ru, cpv.gov.ru, ktru-code.ru
5. Найди актуальную информацию о кодах КТРУ и сопоставь характеристики товара с требованиями кодов

## Правила определения:
1. Анализируй все поля JSON, особое внимание обрати на:
   - title (полное наименование товара)
   - description (описание товара)
   - category и parent_category (категории товара)
   - attributes (ключевые характеристики)
   - brand (производитель)
2. Для корректного определения кода КТРУ обязательно учитывай:
   - Точное соответствие типа товара (например, для батареек: солевые/щелочные/литиевые)
   - Типоразмер (например, AAA, AA, C, D для батареек)
   - Технические характеристики (напряжение, емкость и т.д.)
   - Специфические особенности товара, указанные в описании
3. Код КТРУ должен иметь формат XX.XX.XX.XXX-XXXXXXXX, где первые цифры соответствуют ОКПД2, а после дефиса - уникальный идентификатор в КТРУ.

## Формат ответа:
- Если определен один точный код с уверенностью >95%, выведи только этот код КТРУ, без пояснений
- Если невозможно определить точный код, выведи только фразу "код не найден"

JSON товара: {product_json}"""

    async def process_product_batch(self, products: List[Dict[str, Any]]) -> str:
        """
        Обрабатывает батч товаров для определения кодов КТРУ

        Args:
            products: Список товаров для обработки

        Returns:
            str: ID батча
        """
        batch_id = f"product_batch_{uuid.uuid4()}"
        logger.info(f"Начало обработки батча товаров {batch_id}, количество товаров: {len(products)}")

        # Создаем запись батча в Redis
        batch_key = f"product_batch:{batch_id}"
        pipe = self.task_store.redis.pipeline()
        pipe.hset(batch_key, mapping={
            "status": "pending",
            "created_at": time.time(),
            "updated_at": time.time(),
            "product_count": len(products),
            "processed_count": 0,
            "completed": "false"
        })

        # Добавляем батч в список активных батчей
        pipe.zadd("product_batches:active", {batch_id: time.time()})

        # Устанавливаем TTL для батча
        pipe.expire(batch_key, settings.TASK_PENDING_TTL)

        # Выполняем команды
        pipe.execute()

        # Сохраняем товары в Redis
        for i, product in enumerate(products):
            # Изменено с _id на mongo_id, с учетом обратной совместимости
            product_id = ""
            if "mongo_id" in product and "$oid" in product["mongo_id"]:
                product_id = str(product["mongo_id"]["$oid"])
            elif "_id" in product and "$oid" in product["_id"]:
                product_id = str(product["_id"]["$oid"])
            else:
                product_id = f"product_{uuid.uuid4()}"

            product_key = f"product:{batch_id}:{product_id}"

            # Сохраняем исходный товар
            self.task_store.redis.set(
                product_key,
                json.dumps(product),
                ex=settings.TASK_PENDING_TTL
            )

            # Добавляем в список товаров батча
            self.task_store.redis.sadd(f"product_batch:{batch_id}:products", product_id)
            self.task_store.redis.expire(f"product_batch:{batch_id}:products", settings.TASK_PENDING_TTL)

        # Запускаем асинхронную обработку
        asyncio.create_task(self._process_product_batch(batch_id, products))

        return batch_id

    async def _process_product_batch(self, batch_id: str, products: List[Dict[str, Any]]):
        """
        Внутренний метод для асинхронной обработки батча товаров

        Args:
            batch_id: ID батча
            products: Список товаров для обработки
        """
        logger.info(f"Запуск асинхронной обработки батча {batch_id}")

        try:
            # Устанавливаем статус "processing"
            self.task_store.redis.hset(f"product_batch:{batch_id}", "status", "processing")

            # Обрабатываем каждый товар
            for i, product in enumerate(products):
                # Изменено с _id на mongo_id, с учетом обратной совместимости
                product_id = ""
                if "mongo_id" in product and "$oid" in product["mongo_id"]:
                    product_id = str(product["mongo_id"]["$oid"])
                elif "_id" in product and "$oid" in product["_id"]:
                    product_id = str(product["_id"]["$oid"])
                else:
                    product_id = f"product_{i}"

                try:
                    # Обогащаем данные о товаре через сервис поиска
                    enriched_product = await self.search_service.enrich_product_data(product)

                    # Подготавливаем запрос для Anthropic
                    product_json = json.dumps(enriched_product)
                    prompt = self.ktru_prompt_template.format(product_json=product_json)

                    # Отправляем запрос к Anthropic API
                    result = await self.anthropic_client.create_batch(product_id, prompt)
                    batch_anthropic_id = result["batch_id"]

                    # Сохраняем ID батча Anthropic
                    product_key = f"product:{batch_id}:{product_id}"
                    self.task_store.redis.hset(f"product_batch:{batch_id}", f"anthropic_batch:{product_id}",
                                               batch_anthropic_id)

                    # Ожидаем завершения обработки
                    ktru_code = await self._wait_for_anthropic_result(batch_anthropic_id, product_id)

                    # Обновляем товар с кодом КТРУ
                    product_data = json.loads(self.task_store.redis.get(product_key))
                    product_data["ktru_code"] = ktru_code if ktru_code != "код не найден" else None

                    # Сохраняем обновленный товар
                    self.task_store.redis.set(product_key, json.dumps(product_data))

                    # Увеличиваем счетчик обработанных товаров
                    self.task_store.redis.hincrby(f"product_batch:{batch_id}", "processed_count", 1)

                    logger.info(f"Товар {product_id} в батче {batch_id} обработан, код КТРУ: {ktru_code}")

                except Exception as e:
                    logger.exception(f"Ошибка при обработке товара {product_id} в батче {batch_id}: {str(e)}")

                    # Отмечаем ошибку для товара
                    self.task_store.redis.hset(
                        f"product_batch:{batch_id}",
                        f"error:{product_id}",
                        str(e)
                    )

                    # Увеличиваем счетчик обработанных товаров (даже при ошибке)
                    self.task_store.redis.hincrby(f"product_batch:{batch_id}", "processed_count", 1)

            # Отмечаем батч как завершенный
            pipe = self.task_store.redis.pipeline()
            pipe.hset(f"product_batch:{batch_id}", "status", "completed")
            pipe.hset(f"product_batch:{batch_id}", "completed", "true")
            pipe.hset(f"product_batch:{batch_id}", "updated_at", time.time())

            # Перемещаем из активных в завершенные
            pipe.zrem("product_batches:active", batch_id)
            pipe.zadd("product_batches:completed", {batch_id: time.time()})

            # Обновляем TTL
            pipe.expire(f"product_batch:{batch_id}", settings.TASK_COMPLETED_TTL)
            pipe.expire(f"product_batch:{batch_id}:products", settings.TASK_COMPLETED_TTL)

            pipe.execute()

            logger.info(f"Батч {batch_id} полностью обработан")

        except Exception as e:
            logger.exception(f"Ошибка при обработке батча {batch_id}: {str(e)}")

            # Отмечаем батч как завершенный с ошибкой
            pipe = self.task_store.redis.pipeline()
            pipe.hset(f"product_batch:{batch_id}", "status", "failed")
            pipe.hset(f"product_batch:{batch_id}", "completed", "true")
            pipe.hset(f"product_batch:{batch_id}", "error", str(e))
            pipe.hset(f"product_batch:{batch_id}", "updated_at", time.time())

            # Перемещаем из активных в завершенные
            pipe.zrem("product_batches:active", batch_id)
            pipe.zadd("product_batches:failed", {batch_id: time.time()})

            # Обновляем TTL
            pipe.expire(f"product_batch:{batch_id}", settings.TASK_FAILED_TTL)
            pipe.expire(f"product_batch:{batch_id}:products", settings.TASK_FAILED_TTL)

            pipe.execute()

    async def _wait_for_anthropic_result(self, batch_id: str, product_id: str) -> str:
        """
        Ожидает результат обработки товара от Anthropic API

        Args:
            batch_id: ID батча Anthropic
            product_id: ID товара

        Returns:
            str: Код КТРУ или "код не найден"
        """
        max_attempts = 30  # Максимальное количество попыток
        delay = 2  # Начальная задержка между попытками в секундах

        for attempt in range(max_attempts):
            try:
                # Проверяем статус батча
                batch_status = await self.anthropic_client.get_batch_status(batch_id)

                # Если обработка завершена, получаем результаты
                if batch_status["status"] == "ended":
                    batch_results = await self.anthropic_client.get_batch_results(batch_id)

                    if product_id in batch_results:
                        result_data = batch_results[product_id]

                        if result_data["status"] == "completed":
                            # Получаем текст ответа
                            content = result_data.get("content", "")

                            # Очищаем текст от лишних символов
                            ktru_code = content.strip()

                            # Проверяем формат кода КТРУ или наличие фразы "код не найден"
                            if ktru_code == "код не найден" or self._is_valid_ktru_code(ktru_code):
                                return ktru_code
                            else:
                                logger.warning(f"Неожиданный формат ответа для товара {product_id}: {content}")
                                return "код не найден"
                        else:
                            logger.error(
                                f"Ошибка обработки товара {product_id}: {result_data.get('error', 'Неизвестная ошибка')}")
                            return "код не найден"
                    else:
                        logger.error(f"Результат для товара {product_id} не найден в батче {batch_id}")
                        return "код не найден"

                # Если обработка еще не завершена, ждем
                delay = min(delay * 1.5, 60)  # Экспоненциальная задержка, максимум 60 секунд
                await asyncio.sleep(delay)

            except Exception as e:
                logger.exception(f"Ошибка при получении результата для товара {product_id}: {str(e)}")
                delay = min(delay * 1.5, 60)
                await asyncio.sleep(delay)

        logger.error(f"Превышено максимальное количество попыток получения результата для товара {product_id}")
        return "код не найден"

    def _is_valid_ktru_code(self, code: str) -> bool:
        """
        Проверяет, соответствует ли код формату КТРУ

        Args:
            code: Код для проверки

        Returns:
            bool: True, если код соответствует формату КТРУ
        """
        # Формат: XX.XX.XX.XXX-XXXXXXXX
        pattern = r'^\d{2}\.\d{2}\.\d{2}\.\d{3}-\d{8}$'
        return bool(re.match(pattern, code))

    async def get_batch_status(self, batch_id: str, include_products: bool = False) -> Dict[str, Any]:
        """
        Получает статус обработки батча

        Args:
            batch_id: ID батча
            include_products: Включать ли информацию о товарах

        Returns:
            Dict[str, Any]: Статус батча
        """
        # Проверяем существование батча
        batch_key = f"product_batch:{batch_id}"

        if not self.task_store.redis.exists(batch_key):
            return {
                "batch_id": batch_id,
                "status": "not_found",
                "product_count": 0,
                "processed_count": 0,
                "completed": True,
                "error": "Батч не найден"
            }

        # Получаем информацию о батче
        batch_data = self.task_store.redis.hgetall(batch_key)

        # Преобразуем байты в строки
        batch_info = {k.decode('utf-8'): v.decode('utf-8') for k, v in batch_data.items()}

        # Формируем базовый ответ
        response = {
            "batch_id": batch_id,
            "status": batch_info.get("status", "unknown"),
            "product_count": int(batch_info.get("product_count", "0")),
            "processed_count": int(batch_info.get("processed_count", "0")),
            "completed": batch_info.get("completed", "false") == "true"
        }

        # Добавляем ошибку, если есть
        if "error" in batch_info:
            response["error"] = batch_info["error"]

        # Если требуется, добавляем информацию о товарах
        if include_products and response["status"] in ["completed", "failed"]:
            products = []

            # Получаем список ID товаров в батче
            product_ids = self.task_store.redis.smembers(f"product_batch:{batch_id}:products")

            for product_id_bytes in product_ids:
                product_id = product_id_bytes.decode('utf-8')
                product_key = f"product:{batch_id}:{product_id}"

                if self.task_store.redis.exists(product_key):
                    product_data = self.task_store.redis.get(product_key)
                    product = json.loads(product_data)
                    products.append(product)

            response["products"] = products

        return response