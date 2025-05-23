from pydantic import BaseModel, Field
from typing import Optional

class ProcessingRequest(BaseModel):
    """
    Запрос на обработку текста
    """
    text: str = Field(..., description="Текст для обработки")
    document_id: Optional[str] = Field(None, description="ID документа (для отслеживания)")
    prompt_template: Optional[str] = Field(None, description="Шаблон промпта")