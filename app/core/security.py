from fastapi import Depends, HTTPException, Header, status
from app.config import settings

def verify_api_key(x_api_key: str = Header(None)):
    """
    Проверяет API ключ в заголовке запроса
    """
    if x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный API ключ",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    return x_api_key