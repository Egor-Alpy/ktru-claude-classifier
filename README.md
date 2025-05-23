# KTRU Claude Classifier

Сервис для пакетной обработки товаров и определения кодов КТРУ с использованием Anthropic Claude API.

## Возможности

- Пакетная загрузка и обработка товаров для определения кодов КТРУ
- Асинхронная обработка с использованием Anthropic Batches API
- REST API для интеграции с другими системами
- Скрипт командной строки для обработки больших файлов

## Установка и запуск

### Предварительные требования

- Docker и Docker Compose
- Ключ API Anthropic Claude

### Запуск с использованием Docker Compose

1. Клонируйте репозиторий:

```bash
git clone <repository-url>
cd ktru-claude-classifier
```

2. Создайте файл .env с необходимыми переменными окружения:

```
API_KEY=your_secret_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ANTHROPIC_MODEL=claude-3-7-sonnet-20250219
```

3. Запустите сервис с помощью Docker Compose:

```bash
docker-compose up -d
```

4. Проверьте, что сервис работает, открыв в браузере http://localhost:8000/docs

### Установка для разработки

1. Клонируйте репозиторий:

```bash
git clone <repository-url>
cd ktru-claude-classifier
```

2. Создайте виртуальное окружение и установите зависимости:

```bash
python -m venv venv
source venv/bin/activate  # На Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Создайте файл .env с настройками:

```
API_KEY=your_secret_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ANTHROPIC_MODEL=claude-3-7-sonnet-20250219
REDIS_URL=redis://localhost:6379/0
```

4. Запустите Redis:

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

5. Запустите сервис:

```bash
uvicorn app.main:app --reload
```

## Использование API

### Отправка батча товаров на обработку

```bash
curl -X POST "http://localhost:8000/api/v1/products/batch" \
     -H "X-API-Key: your_secret_api_key_here" \
     -H "Content-Type: application/json" \
     -d '{
       "products": [
         {
           "_id": { "$oid": "6823c22ba470eaaf4b441b1a" },
           "title": "Ручка гелевая Pilot, BL-G6-5 Alfagel",
           "description": "Автоматическая многоразовая ручка...",
           "article": "009943",
           "brand": "Pilot",
           "country_of_origin": "Нет данных",
           "warranty_months": "Нет данных",
           "category": "Ручки гелевые",
           "created_at": "16.05.2025 07:20",
           "attributes": [
             { "attr_name": "Цвет чернил", "attr_value": "Синий" },
             { "attr_name": "Толщина линии", "attr_value": "0,3 мм" }
           ],
           "suppliers": [...]
         }
       ]
     }'
```

Ответ:

```json
{
  "batch_id": "product_batch_123e4567-e89b-12d3-a456-426614174000",
  "status": "pending",
  "product_count": 1,
  "processed_count": 0
}
```

### Проверка статуса обработки батча

```bash
curl -X GET "http://localhost:8000/api/v1/products/batch/product_batch_123e4567-e89b-12d3-a456-426614174000?include_products=true" \
     -H "X-API-Key: your_secret_api_key_here"
```

Ответ:

```json
{
  "batch_id": "product_batch_123e4567-e89b-12d3-a456-426614174000",
  "status": "completed",
  "product_count": 1,
  "processed_count": 1,
  "completed": true,
  "products": [
    {
      "_id": { "$oid": "6823c22ba470eaaf4b441b1a" },
      "title": "Ручка гелевая Pilot, BL-G6-5 Alfagel",
      "description": "Автоматическая многоразовая ручка...",
      "article": "009943",
      "brand": "Pilot",
      "country_of_origin": "Нет данных",
      "warranty_months": "Нет данных",
      "category": "Ручки гелевые",
      "created_at": "16.05.2025 07:20",
      "attributes": [...],
      "suppliers": [...],
      "ktru_code": "32.99.12.120-00000001"
    }
  ]
}
```

## Использование скрипта командной строки

Для обработки большого количества товаров из файла можно использовать скрипт командной строки:

```bash
python scripts/process_products.py path/to/products.json --api-key your_api_key
```

Дополнительные параметры:

```bash
python scripts/process_products.py --help
```

## Структура проекта

```
app/
  ├── api/               # Эндпоинты API
  ├── ai/                # Клиенты AI API
  ├── core/              # Базовые компоненты
  ├── schemas/           # Модели данных
  ├── services/          # Бизнес-логика
  ├── storage/           # Хранилище данных
  └── main.py            # Точка входа приложения
prompts/                 # Шаблоны промптов
scripts/                 # Утилиты командной строки
```

## Настройка промптов

Шаблоны промптов хранятся в директории `prompts/` в формате YAML. Шаблон для определения кодов КТРУ:

```yaml
text: |
  Я предоставлю тебе JSON-файл с описанием товара. Твоя задача - определить единственный точный код КТРУ...
  
  JSON товара: {text}
```

## Troubleshooting

### Проблемы с запуском Docker

Если у вас возникают проблемы с запуском Docker, проверьте:

1. Запущен ли Docker Desktop (на Windows/Mac)
2. Убедитесь, что порт 8000 не занят другим приложением
3. Проверьте логи контейнера: `docker-compose logs -f api`

### Ошибки при обработке товаров

1. Проверьте корректность формата JSON-данных товаров
2. Убедитесь, что API ключ Anthropic действителен и не истек срок его действия
3. Проверьте, что у вас достаточно токенов в аккаунте Anthropic

## Лицензия

MIT