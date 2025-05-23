FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Create prompts directory if it doesn't exist
RUN mkdir -p /app/prompts

# Create a default prompt template
RUN echo "text: |\n  Я предоставлю тебе JSON-файл с описанием товара. Твоя задача - определить единственный точный код КТРУ (Каталог товаров, работ, услуг) для этого товара. Если ты не можешь определить код с высокой уверенностью (более 95%), ответь только \"код не найден\".\n\n  ## Правила определения:\n  1. Анализируй все поля JSON, особое внимание обрати на:\n     - title (полное наименование товара)\n     - description (описание товара)\n     - category и parent_category (категории товара)\n     - attributes (ключевые характеристики)\n     - brand (производитель)\n  2. Для корректного определения кода КТРУ обязательно учитывай:\n     - Точное соответствие типа товара (например, для батареек: солевые/щелочные/литиевые)\n     - Типоразмер (например, AAA, AA, C, D для батареек)\n     - Технические характеристики (напряжение, емкость и т.д.)\n     - Специфические особенности товара, указанные в описании\n  3. Код КТРУ должен иметь формат XX.XX.XX.XXX-XXXXXXXX, где первые цифры соответствуют ОКПД2, а после дефиса - уникальный идентификатор в КТРУ.\n\n  ## Формат ответа:\n  - Если определен один точный код с уверенностью >95%, выведи только этот код КТРУ, без пояснений\n  - Если невозможно определить точный код, выведи только фразу \"код не найден\"\n\n  JSON товара: {text}" > /app/prompts/ktru_detection.yaml

# Expose the port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]