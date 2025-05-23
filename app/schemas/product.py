# api-service/app/schemas/product.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

class SupplierOffer(BaseModel):
    """Предложение поставщика"""
    price: List[Dict[str, Any]] = Field(..., description="Ценовая информация")
    stock: str = Field(..., description="Наличие на складе")
    delivery_time: str = Field(..., description="Время доставки")
    package_info: str = Field(..., description="Информация об упаковке")
    purchase_url: str = Field(..., description="URL для покупки")

class Supplier(BaseModel):
    """Поставщик товара"""
    dealer_id: str = Field(..., description="ID дилера")
    supplier_name: str = Field(..., description="Название поставщика")
    supplier_tel: str = Field(..., description="Телефон поставщика")
    supplier_address: str = Field(..., description="Адрес поставщика")
    supplier_description: str = Field(..., description="Описание поставщика")
    supplier_offers: List[SupplierOffer] = Field(..., description="Предложения поставщика")

class Attribute(BaseModel):
    """Атрибут товара"""
    attr_name: str = Field(..., description="Название атрибута")
    attr_value: str = Field(..., description="Значение атрибута")

class SKUItem(BaseModel):
    """Модель товара SKU"""
    _id: Dict[str, str] = Field(..., description="MongoDB ID")
    title: str = Field(..., description="Название товара")
    description: str = Field(..., description="Описание товара")
    article: str = Field(..., description="Артикул товара")
    brand: str = Field(..., description="Бренд")
    country_of_origin: str = Field(..., description="Страна происхождения")
    warranty_months: str = Field(..., description="Гарантия в месяцах")
    category: str = Field(..., description="Категория товара")
    created_at: str = Field(..., description="Дата создания")
    attributes: List[Attribute] = Field(..., description="Атрибуты товара")
    suppliers: List[Supplier] = Field(..., description="Поставщики")
    ktru_code: Optional[str] = Field(None, description="Код КТРУ")

class SKUBatchRequest(BaseModel):
    """Запрос на батчевую обработку SKU"""
    items: List[SKUItem] = Field(..., description="Список товаров для обработки")
    batch_size: Optional[int] = Field(100, description="Размер батча", ge=1, le=1000)
    prompt_template: Optional[str] = Field("ktru_classification", description="Шаблон промпта")

class SKUBatchResponse(BaseModel):
    """Ответ на батчевую обработку SKU"""
    batch_id: str = Field(..., description="ID батча Anthropic")
    task_id: str = Field(..., description="ID задачи")
    total_items: int = Field(..., description="Общее количество товаров")
    status: str = Field(..., description="Статус обработки")

class SKUProcessingResult(BaseModel):
    """Результат обработки SKU"""
    task_id: str = Field(..., description="ID задачи")
    batch_id: str = Field(..., description="ID батча")
    status: str = Field(..., description="Статус обработки")
    processed_items: Optional[List[SKUItem]] = Field(None, description="Обработанные товары")
    failed_items: Optional[List[Dict[str, Any]]] = Field(None, description="Товары с ошибками")
    total_processed: int = Field(0, description="Количество обработанных")
    total_failed: int = Field(0, description="Количество с ошибками")
    processing_time: Optional[float] = Field(None, description="Время обработки в секундах")