from langchain_core.messages import AIMessageChunk
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import CheckpointTuple
from app.utils.checkpointer_handler import checkpointer
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

    def get_history(self, thread_id):
        config = RunnableConfig(configurable={"thread_id": thread_id})
        checkpoint_tuple = checkpointer.get_tuple(config)
        return convert_state_to_messages(checkpoint_tuple)

def convert_state_to_messages(checkpoint_tuple: CheckpointTuple):
    messages = checkpoint_tuple.checkpoint["channel_values"]["messages"]
    print(messages)
    return messages

chat_service = ChatService()

if __name__ == "__main__":
    print(chat_service.get_history("sess_1781506489579"))