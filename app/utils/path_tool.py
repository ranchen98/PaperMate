"""
为整个工程提供统一的绝对路径
"""
import os

def get_project_root() -> str:
    """
    获取工程所在的根目录
    :return: 工程所在的根目录(str)
    """
    current_file = os.path.abspath(__file__)
    utils_dir = os.path.dirname(current_file)
    app_dir = os.path.dirname(utils_dir)
    project_root = os.path.dirname(app_dir)
    return project_root

def get_abs_path(*parts: str) -> str:
    """
    传入相对路径分段，返回绝对路径。跨平台兼容 Windows 反斜杠。
    :param parts: 相对路径分段，例如 ("resources", "db")；也兼容传入 "resources\\db" 这种单段写法
    :return: 绝对路径(str)
    """
    project_root = get_project_root()
    normalized = [p.replace("\\", "/") for p in parts]
    return os.path.join(project_root, *normalized)