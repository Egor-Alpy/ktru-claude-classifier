import logging
import aiohttp
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class SearchService:
    """Сервис для обогащения данных о товаре через веб-поиск"""

    async def enrich_product_data(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обогащает данные о товаре информацией из веб-поиска

        Args:
            product: Данные о товаре

        Returns:
            Dict[str, Any]: Обогащенные данные о товаре
        """
        title = product.get("title", "")
        category = product.get("category", "")
        brand = product.get("brand", "")

        # Извлекаем ключевые атрибуты
        attributes = []
        for attr in product.get("attributes", []):
            attr_name = attr.get("attr_name", "")
            attr_value = attr.get("attr_value", "")
            if attr_name and attr_value:
                attributes.append(f"{attr_name}: {attr_value}")

        attributes_str = ", ".join(attributes)

        # Формируем поисковый запрос
        search_query = f"КТРУ код ОКПД2 {category} {title} {brand} {attributes_str}"
        logger.info(f"Поисковый запрос для товара: {search_query}")

        # Здесь будет возвращаться обогащенный продукт.
        # В реальной реализации здесь был бы код для поиска в интернете,
        # но мы полагаемся на инструменты поиска Claude, которые уже интегрированы
        # через anthropic_client.py

        return product

    async def _fetch_page(self, url: str) -> Optional[str]:
        """
        Получает содержимое страницы по URL

        Args:
            url: URL страницы

        Returns:
            Optional[str]: Содержимое страницы или None в случае ошибки
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        logger.warning(f"Ошибка при загрузке страницы {url}: {response.status}")
                        return None
        except Exception as e:
            logger.warning(f"Ошибка при загрузке {url}: {str(e)}")
            return None