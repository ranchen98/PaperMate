from app.utils.config_handler import prompt_config
from app.utils.path_tool import get_abs_path
from app.utils.logger_handler import logger

def _load_prompt(config_key: str):
    try:
        prompt_path = get_abs_path(prompt_config[config_key])
    except KeyError as e:
        logger.error(f"[load_prompt]在yaml配置中没有 {config_key} 配置项")
        raise e
    try:
        return open(prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[load_prompt]解析{config_key}出错: {str(e)}")
        raise e

def load_system_prompts():
    return _load_prompt("system_prompt_path")

def load_rag_summarize_prompt():
    return _load_prompt("rag_summarize_prompt_path")

def load_report_prompt():
    return _load_prompt("report_prompt_path")

def load_summary_prompt():
    return _load_prompt("summary_prompt_path")
