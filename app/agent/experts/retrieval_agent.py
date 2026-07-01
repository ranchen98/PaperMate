"""检索 Agent：知识库正文检索 + 元数据查询 + 联网检索。

绑定 4 个工具：search_paper_content / get_paper_chunk_context / query_paper_metadata / web_search。
仅负责"取信息"，不撰写最终成稿。
"""
from langchain.agents import create_agent

from app.agent.model.factory import retrieval_model
from app.agent.tools.middleware import (
    make_agent_tag_middleware,
    monitor_before_model,
    monitor_tool,
    summarize_middleware,
)
from app.agent.tools.tool import (
    get_paper_chunk_context,
    query_paper_metadata,
    search_paper_content,
    web_search,
)
from app.utils.prompt_loader import load_retrieval_prompt

retrieval_agent = create_agent(
    model=retrieval_model,
    system_prompt=load_retrieval_prompt(),
    tools=[
        search_paper_content,
        get_paper_chunk_context,
        query_paper_metadata,
        web_search,
    ],
    middleware=[
        monitor_tool,
        monitor_before_model,
        summarize_middleware,
        make_agent_tag_middleware("retrieval"),
    ],
    name="retrieval_agent",
)
