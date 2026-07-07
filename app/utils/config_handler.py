import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.utils.path_tool import get_abs_path

ENV_PATH = get_abs_path(".env")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_PATH), env_file_encoding='utf-8', extra='ignore')

    DASHSCOPE_API_KEY: str
    DASHSCOPE_BASE_URL: str
    TAVILY_API_KEY: str
    ES_HOST: str = "http://localhost:9200"
    ES_PORT: str = "9200"
    ES_USERNAME: str | None = None
    ES_PASSWORD: str | None = None
    MINERU_URL: str
    MINERU_TOKEN: str
    JWT_SECRET: str
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7
    # 每日配额（达到阈值时才向用户提示，前端无需主动显式提醒）
    DAILY_REGISTER_LIMIT: int = 3        # 每天最多新注册用户数（全局）
    DAILY_AGENT_CALL_LIMIT: int = 10     # 每用户每天最多调用 Agent (single/multi) 次数
    DAILY_PAPER_UPLOAD_LIMIT: int = 10   # 每用户每天最多上传论文数

env = Settings()

def _load_yaml_config(config_path: str):
    with open(config_path, "r", encoding='utf-8') as f:
        return yaml.load(f, Loader=yaml.FullLoader)

agent_config = _load_yaml_config(get_abs_path("config/agent.yaml"))
prompt_config = _load_yaml_config(get_abs_path("config/prompt.yaml"))
es_config = _load_yaml_config(get_abs_path("config/es.yaml"))