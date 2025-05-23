from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

class ProductAttribute(BaseModel):
    """Атрибут товара"""
    attr_name: str = Field(..., description="Название атрибута")
    attr_value: str = Field(..., description="Значение атрибута")

class SupplierOffer(BaseModel):
    """Предложение поставщика"""
    price: List[Dict[str, Any]] = Field(..., description="Информация о цене")
    stock: str = Field(..., description="Информация о наличии")
    delivery_time: str = Field(..., description="Время доставки")
    package_info: str = Field(..., description="Информация об упаковке")
    purchase_url: str = Field(..., description="URL для покупки")

class Supplier(BaseModel):
    """Информация о поставщике"""
    dealer_id: str = Field(..., description="ID дилера")
    supplier_name: str = Field(..., description="Название поставщика")
    supplier_tel: str = Field(..., description="Телефон поставщика")
    supplier_address: str = Field(..., description="Адрес поставщика")
    supplier_description: str = Field(..., description="Описание поставщика")
    supplier_offers: List[SupplierOffer] = Field(..., description="Предложения поставщика")

class Product(BaseModel):
    """Модель товара для обработки"""
    # Изменено _id на mongo_id для избежания конфликта с Pydantic
    mongo_id: Dict[str, Any] = Field(..., description="Идентификатор товара в MongoDB")
    title: str = Field(..., description="Название товара")
    description: str = Field(..., description="Описание товара")
    article: str = Field(..., description="Артикул товара")
    brand: str = Field(..., description="Бренд товара")
    country_of_origin: str = Field(..., description="Страна происхождения")
    warranty_months: str = Field(..., description="Гарантийный срок в месяцах")
    category: str = Field(..., description="Категория товара")
    created_at: str = Field(..., description="Дата создания")
    attributes: List[ProductAttribute] = Field(..., description="Атрибуты товара")
    suppliers: List[Supplier] = Field(..., description="Поставщики товара")
    ktru_code: Optional[str] = Field(None, description="Код КТРУ")

class ProductBatchRequest(BaseModel):
    """Запрос на обработку батча товаров"""
    products: List[Dict[str, Any]] = Field(..., description="Список товаров для обработки")

class ProductBatchResponse(BaseModel):
    """Ответ на запрос обработки батча товаров"""
    batch_id: str = Field(..., description="ID батча")
    status: str = Field("pending", description="Статус обработки")
    product_count: int = Field(..., description="Количество товаров в батче")
    processed_count: int = Field(0, description="Количество обработанных товаров")

class ProductBatchStatusResponse(BaseModel):
    """Ответ на запрос статуса батча товаров"""
    batch_id: str = Field(..., description="ID батча")
    status: str = Field(..., description="Статус обработки")
    product_count: int = Field(..., description="Количество товаров в батче")
    processed_count: int = Field(..., description="Количество обработанных товаров")
    completed: bool = Field(..., description="Признак завершения обработки")
    products: Optional[List[Dict[str, Any]]] = Field(None, description="Обработанные товары с кодами КТРУ")
    error: Optional[str] = Field(None, description="Ошибка, если есть")