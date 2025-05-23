#!/usr/bin/env python
# scripts/process_products.py
import argparse
import asyncio
import json
import os
import sys
import time
from typing import List, Dict, Any
import logging
import aiohttp

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Константы
MAX_BATCH_SIZE = 50
POLL_INTERVAL = 10  # секунды между проверками статуса


async def process_file(file_path: str, api_url: str, api_key: str, output_dir: str):
    """
    Обрабатывает файл с товарами

    Args:
        file_path: Путь к файлу с товарами (JSON или JSONL)
        api_url: URL API сервиса
        api_key: API ключ
        output_dir: Директория для сохранения результатов
    """
    logger.info(f"Обработка файла: {file_path}")

    # Создаем директорию для результатов, если не существует
    os.makedirs(output_dir, exist_ok=True)

    # Загружаем товары из файла
    products = load_products(file_path)
    logger.info(f"Загружено {len(products)} товаров")

    # Разбиваем товары на батчи
    batches = [products[i:i + MAX_BATCH_SIZE] for i in range(0, len(products), MAX_BATCH_SIZE)]
    logger.info(f"Разбито на {len(batches)} батчей")

    # Обрабатываем каждый батч
    batch_results = []
    for i, batch in enumerate(batches):
        logger.info(f"Обработка батча {i + 1}/{len(batches)}, размер: {len(batch)}")

        # Отправляем батч на обработку
        batch_id = await submit_batch(batch, api_url, api_key)
        logger.info(f"Батч {i + 1} отправлен, ID: {batch_id}")

        # Ожидаем завершения обработки
        batch_result = await wait_for_completion(batch_id, api_url, api_key)
        logger.info(f"Батч {i + 1} обработан, получено {len(batch_result)} товаров с кодами КТРУ")

        # Сохраняем результаты
        batch_results.extend(batch_result)

        # Сохраняем промежуточные результаты
        save_results(batch_results, os.path.join(output_dir, f"results_partial_{i + 1}.json"))

    # Сохраняем итоговые результаты
    save_results(batch_results, os.path.join(output_dir, "results_final.json"))
    logger.info(f"Обработка завершена, всего обработано {len(batch_results)} товаров")

    return batch_results


def load_products(file_path: str) -> List[Dict[str, Any]]:
    """
    Загружает товары из файла

    Args:
        file_path: Путь к файлу (JSON или JSONL)

    Returns:
        List[Dict[str, Any]]: Список товаров
    """
    products = []

    with open(file_path, 'r', encoding='utf-8') as f:
        # Определяем тип файла по содержимому
        first_line = f.readline().strip()
        f.seek(0)  # Возвращаемся в начало файла

        try:
            if first_line.startswith('['):
                # Формат JSON-массива
                products = json.load(f)
            elif first_line.startswith('{'):
                # Формат JSONL (каждая строка - отдельный JSON-объект)
                for line in f:
                    line = line.strip()
                    if line:  # Пропускаем пустые строки
                        products.append(json.loads(line))
            else:
                raise ValueError(f"Неподдерживаемый формат файла: {file_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Ошибка при парсинге JSON: {str(e)}")

    return products


def save_results(products: List[Dict[str, Any]], file_path: str):
    """
    Сохраняет результаты в файл

    Args:
        products: Список обработанных товаров
        file_path: Путь к файлу для сохранения
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


async def submit_batch(products: List[Dict[str, Any]], api_url: str, api_key: str) -> str:
    """
    Отправляет батч товаров на обработку

    Args:
        products: Список товаров
        api_url: URL API сервиса
        api_key: API ключ

    Returns:
        str: ID батча
    """
    url = f"{api_url}/api/v1/products/batch"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "products": products
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 202:
                response_text = await response.text()
                raise Exception(f"Ошибка при отправке батча: {response.status}, {response_text}")

            result = await response.json()
            return result["batch_id"]


async def wait_for_completion(batch_id: str, api_url: str, api_key: str) -> List[Dict[str, Any]]:
    """
    Ожидает завершения обработки батча

    Args:
        batch_id: ID батча
        api_url: URL API сервиса
        api_key: API ключ

    Returns:
        List[Dict[str, Any]]: Список обработанных товаров
    """
    url = f"{api_url}/api/v1/products/batch/{batch_id}?include_products=true"
    headers = {
        "X-API-Key": api_key
    }

    while True:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    response_text = await response.text()
                    raise Exception(f"Ошибка при получении статуса батча: {response.status}, {response_text}")

                result = await response.json()

                if result["completed"]:
                    if result["status"] == "failed":
                        raise Exception(f"Ошибка при обработке батча: {result.get('error', 'Неизвестная ошибка')}")

                    return result.get("products", [])

                # Выводим прогресс
                logger.info(
                    f"Статус батча {batch_id}: {result['status']}, обработано {result['processed_count']}/{result['product_count']}")

                # Ждем перед следующей проверкой
                await asyncio.sleep(POLL_INTERVAL)


async def main():
    parser = argparse.ArgumentParser(description="Скрипт для пакетной обработки товаров и определения кодов КТРУ")
    parser.add_argument("file", help="Путь к файлу с товарами (JSON или JSONL)")
    parser.add_argument("--api-url", default="http://localhost:8000", help="URL API сервиса")
    parser.add_argument("--api-key", required=True, help="API ключ")
    parser.add_argument("--output-dir", default="./results", help="Директория для сохранения результатов")

    args = parser.parse_args()

    try:
        await process_file(args.file, args.api_url, args.api_key, args.output_dir)
    except Exception as e:
        logger.exception(f"Ошибка при обработке файла: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())