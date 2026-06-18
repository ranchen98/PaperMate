from datetime import datetime

from langchain.agents.middleware.types import AgentState
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END

from app.business.chat_request import ChatRequest
from app.core.factory import react_agent
from app.utils.checkpointer_handler import checkpointer
from app.utils.logger_handler import logger

def preprocessing_node(state: AgentState)-> dict:
    updated_messages = []
    for msg in state["messages"]:
        # 如果消息还没有时间戳，则注入当前时间
        if isinstance(msg, HumanMessage) and "timestamp" not in msg.additional_kwargs:
            # 注意：Message 是不可变的，需要使用 copy() 或 model_copy()
            msg_copy = msg.model_copy()
            msg_copy.additional_kwargs["timestamp"] = datetime.now().timestamp()
            updated_messages.append(msg_copy)
        else:
            updated_messages.append(msg)
    return {"messages": updated_messages}

def create_chat_agent_graph():
    graph = StateGraph(AgentState)
    # 添加节点
    graph.add_node("preprocessing", preprocessing_node)
    graph.add_node("react_node", react_agent) #将agent做为节点
    # 定义流程
    graph.set_entry_point("preprocessing")
    graph.add_edge("preprocessing", "react_node")
    graph.add_edge("react_node", END)
    return graph.compile(checkpointer=checkpointer)

class ChatAgent:
    def __init__(self):
        self.graph = create_chat_agent_graph()
        logger.debug("[ChatAgent] 初始化成功")

    def stream(self, request:ChatRequest):
        message = request.message
        config = RunnableConfig(configurable={"thread_id": request.thread_id})
        return self.graph.stream(
            input={"messages": [HumanMessage(message)]},
            config= config,
            stream_mode="messages"
        )

    def invoke(self, request:ChatRequest):
        message = request.message
        config = RunnableConfig(configurable={"thread_id": request.thread_id})
        return self.graph.invoke(
            input={"messages": [HumanMessage(message)]},
            config=config,
        )

    def get_state(self, thread_id:str):
        config = RunnableConfig(configurable={"thread_id": thread_id})
        return self.graph.get_state(config)

chat_agent = ChatAgent()

if __name__ == "__main__":
    print(chat_agent.invoke(ChatRequest(thread_id="abc", message="我刚才问了你什么问题")))
    print(chat_agent.get_state(thread_id="abc"))
