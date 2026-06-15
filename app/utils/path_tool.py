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

def get_abs_path(relative_path: str) -> str:
    """
    传入相对路径，返回绝对路径
    :param relative_path: 相对路径
    :return: 绝对路径
    """
    project_root = get_project_root()
    return os.path.join(project_root, relative_path)