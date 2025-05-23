import logging
import yaml
import os
from typing import Dict, Any, Optional

from app.config import settings
from app.core.exceptions import AIException

logger = logging.getLogger(__name__)


class AIService:
    """
    Сервис для работы с AI моделями
    """

    def __init__(self):
        """
        Инициализация сервиса
        """
        self.prompts_dir = settings.PROMPTS_DIR
        self.default_prompt = settings.DEFAULT_PROMPT
        self.callback_url = settings.CALLBACK_URL
        self.callback_secret = settings.CALLBACK_SECRET

    def get_formatted_prompt(
            self,
            text: str,
            prompt_template: Optional[str] = None
    ) -> str:
        """
        Форматирование промпта для обработки текста

        Args:
            text: Текст для обработки
            prompt_template: Имя файла шаблона промпта

        Returns:
            str: Отформатированный промпт

        Raises:
            AIException: При ошибке форматирования
        """
        try:
            # Получаем шаблон промпта
            prompt = self._load_prompt(prompt_template)

            # Заменяем переменные в промпте
            formatted_prompt = prompt.format(text=text)

            # Логируем длину текста и промпта
            logger.info(
                f"Форматирование промпта длиной {len(text)} символов. Шаблон: {prompt_template or self.default_prompt}")

            return formatted_prompt

        except Exception as e:
            logger.exception(f"Ошибка при форматировании промпта: {str(e)}")
            raise AIException(f"Ошибка при форматировании промпта: {str(e)}")

    def _load_prompt(self, prompt_name: Optional[str] = None) -> str:
        """
        Загрузка шаблона промпта

        Args:
            prompt_name: Имя файла шаблона промпта

        Returns:
            str: Текст промпта

        Raises:
            AIException: При отсутствии файла промпта или ошибке загрузки
        """
        # Если имя не указано, используем промпт по умолчанию
        prompt_file = prompt_name or self.default_prompt

        # Добавляем расширение .yaml, если отсутствует
        if not prompt_file.endswith('.yaml'):
            prompt_file += '.yaml'

        # Путь к файлу промпта
        prompt_path = os.path.join(self.prompts_dir, prompt_file)

        # Проверяем существование файла
        if not os.path.exists(prompt_path):
            error_msg = f"Файл промпта не найден: {prompt_path}"
            logger.error(error_msg)
            raise AIException(error_msg)

        try:
            # Загружаем промпт
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_data = yaml.safe_load(f)

            # Проверяем наличие ключа 'text'
            if 'text' not in prompt_data:
                error_msg = f"Отсутствует ключ 'text' в файле промпта: {prompt_path}"
                logger.error(error_msg)
                raise AIException(error_msg)

            return prompt_data['text']

        except yaml.YAMLError as e:
            error_msg = f"Ошибка парсинга YAML в файле промпта {prompt_path}: {str(e)}"
            logger.exception(error_msg)
            raise AIException(error_msg)
        except Exception as e:
            error_msg = f"Ошибка при загрузке промпта {prompt_path}: {str(e)}"
            logger.exception(error_msg)
            raise AIException(error_msg)

    def get_callback_url(self) -> str:
        """
        Получает URL для колбека

        Returns:
            str: URL для колбека
        """
        return self.callback_url

    def get_callback_secret(self) -> str:
        """
        Получает секрет для подписи колбека

        Returns:
            str: Секрет для подписи колбека
        """
        return self.callback_secret