from langchain_core.messages import HumanMessage, AIMessageChunk
from app.agent.chat_agent import get_agent
from app.models import ChatRequest
from app.core.logger import logger

async def chat_streaming_response(request: ChatRequest):
    thread_id = request.id
    message = request.message
    logger.debug(f"chat_streaming_response(): "
                 f"thread_id={thread_id}    "
                 f"message={message}")
    try:
        for chunk, metadata in  get_agent().stream(
                {"messages": [HumanMessage(message)]},
                {"configurable": {"thread_id": thread_id}},
                stream_mode="messages"
        ):
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                logger.debug("AIMessageChunk:" + str(chunk.content))
                yield f"data: {chunk.content}\n\n"
    except Exception as e:
        logger.error(f"chat_streaming_response(): {str(e)}")
        yield f"data: {str(e)}\n\n"