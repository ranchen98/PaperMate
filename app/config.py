from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_path = Path(__file__).resolve().parent.parent / '.env'

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_env_path), env_file_encoding='utf-8', extra='ignore')

    DASHSCOPE_API_KEY: str
    DASHSCOPE_BASE_URL: str
    TAVILY_API_KEY: str
    WEB_SEARCH_MAX_RESULTS: int = 2

config = Settings()