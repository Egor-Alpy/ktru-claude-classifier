# api-service/app/main.py
import logging
import asyncio
from fastapi import FastAPI
from app.api.router import router as api_router
from app.storage.task_store import TaskStore
from app.storage.outbox_store import OutboxStore
from app.services.task_processor import TaskProcessor
from app.services.product_processor import ProductProcessor  # Новый импорт
from app.ai.anthropic_client import AnthropicClient
from app.services.outbox_relay_service import OutboxRelayService
from app.config import settings

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="AI Processing Service",
    description="Сервис для обработки текстов и товаров с помощью моделей AI",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json"
)

# Глобальные объекты
task_store = None
outbox_store = None
task_processor = None
anthropic_client = None
outbox_relay_service = None
product_processor = None  # Новый объект


@app.on_event("startup")
async def startup_event():
    global task_store, outbox_store, task_processor, anthropic_client, outbox_relay_service, product_processor

    # Инициализация хранилища задач
    task_store = TaskStore(settings.REDIS_URL)

    # Инициализация хранилища outbox
    outbox_store = OutboxStore(task_store.redis)

    # Инициализация клиента Anthropic
    anthropic_client = AnthropicClient()

    # Инициализация обработчика задач
    task_processor = TaskProcessor(
        task_store=task_store,
        anthropic_client=anthropic_client,
        outbox_store=outbox_store
    )

    # Инициализация обработчика товаров
    product_processor = ProductProcessor(
        task_store=task_store,
        anthropic_client=anthropic_client,
        outbox_store=outbox_store
    )

    # Инициализация сервиса-релея
    outbox_relay_service = OutboxRelayService(outbox_store)

    # Запуск обработчика задач
    await task_processor.start()

    # Запуск сервиса-релея
    await outbox_relay_service.start()

    logging.info("Сервисы успешно инициализированы")


@app.on_event("shutdown")
async def shutdown_event():
    global task_processor, outbox_relay_service

    if task_processor:
        await task_processor.stop()

    if outbox_relay_service:
        await outbox_relay_service.stop()

    logging.info("Сервисы успешно остановлены")


# Подключение маршрутов
app.include_router(api_router, prefix="/api")