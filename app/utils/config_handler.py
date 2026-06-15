import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.utils.path_tool import get_abs_path

ENV_PATH = get_abs_path(".env")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_PATH), env_file_encoding='utf-8', extra='ignore')

    DASHSCOPE_API_KEY: str
    DASHSCOPE_BASE_URL: str
    TAVILY_API_KEY: str

env = Settings()

def _load_yaml_config(config_path: str):
    with open(config_path, "r", encoding='utf-8') as f:
        return yaml.load(f, Loader=yaml.FullLoader)

rag_config = _load_yaml_config(get_abs_path("config/rag.yaml"))
agent_config = _load_yaml_config(get_abs_path("config/agent.yaml"))
prompt_config = _load_yaml_config(get_abs_path("config/prompts.yaml"))
chroma_config = _load_yaml_config(get_abs_path("config/chroma.yaml"))