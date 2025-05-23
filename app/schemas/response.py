from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class ProcessingResponse(BaseModel):
    """
    Ответ на запрос обработки текста
    """
    request_id: str = Field(..., description="ID запроса")
    batch_id: Optional[str] = Field(None, description="ID пакета Anthropic Batches API")
    status: Optional[str] = Field(None, description="Статус обработки")
    batch_status: Optional[str] = Field(None, description="Статус пакета Anthropic")
    result: Dict[str, Any] = Field(..., description="Результат обработки")
    error: Optional[str] = Field(None, description="Сообщение об ошибке, если есть")
    input_tokens: int = Field(0, description="Количество входных токенов")
    output_tokens: int = Field(0, description="Количество выходных токенов")
    processing_time: float = Field(0, description="Время обработки в секундах")