class APIServiceException(Exception):
    """
    Базовый класс для всех исключений сервиса
    """
    pass

class AIException(APIServiceException):
    """
    Исключение при ошибке взаимодействия с AI API
    """
    def __init__(self, message: str, model: str = None, retry: bool = True):
        self.message = message
        self.model = model
        self.retry = retry
        super().__init__(message)

class StorageException(APIServiceException):
    """
    Исключение при ошибке хранилища
    """
    def __init__(self, message: str, operation: str = None):
        self.message = message
        self.operation = operation
        super().__init__(message)