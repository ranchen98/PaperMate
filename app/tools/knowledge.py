from langchain.tools import tool
from langchain_tavily import TavilySearch
from app.config import Settings

config = Settings()
tavily_search = TavilySearch(
    tavily_api_key= config.TAVILY_API_KEY,
    max_results = config.WEB_SEARCH_MAX_RESULTS,
    topic = "general"
)

@tool
def web_search(query: str):
    """Search the web for information
    Args:
        query (str): The search query
    """
    return tavily_search.invoke(query)