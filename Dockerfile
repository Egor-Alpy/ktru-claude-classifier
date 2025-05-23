FROM python:3.11-slim

WORKDIR /ktru-claude-classifier

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
    PYTHONPATH=/ktru-claude-classifier

# Create prompts directory if it doesn't exist
# Create prompts directory if it doesn't exist
RUN mkdir -p /ktru-claude-classifier/prompts

# Create a default prompt template
RUN echo "text: |..." > /ktru-claude-classifier/prompts/ktru_detection.yaml

# Create a default prompt template
RUN echo "text: |\n  Я предоставлю тебе JSON-файл..." > /ktru-claude-classifier/prompts/ktru_detection.yaml
# Expose the port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]