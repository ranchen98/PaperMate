from langchain_core.messages import HumanMessage, AIMessageChunk
from app.agent.chat_agent import chat_agent
from app.utils.logger_handler import logger
from app.business.chat_request import ChatRequest

class ChatService():
    def chat_streaming_response(self, request: ChatRequest):
        try:
            for chunk, metadata in chat_agent.stream(request):
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    yield f"data: {chunk.content}\n\n"
        except Exception as e:
            logger.error(f"[chat_streaming_response]: {str(e)}")
            yield f"data: {"调用失败"}\n\n"

chat_service = ChatService()