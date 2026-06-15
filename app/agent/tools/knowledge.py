from langchain.tools import tool
from langchain_tavily import TavilySearch
from app.utils.config_handler import env, agent_config

tavily_search = TavilySearch(
    tavily_api_key= env.TAVILY_API_KEY,
    max_results = agent_config["web_search_max_results"],
    topic = "general"
)

@tool
def web_search(query: str):
    """Search the web for information
    Args:
        query (str): The search query
    """
    return tavily_search.invoke(query)