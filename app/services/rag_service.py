from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from app.core.factory import chat_model
from app.services.vector_store_service import VectorStoreService
from app.utils.prompt_loader import load_rag_summarize_prompt

class RagSummarizeService(object):
    def __init__(self):
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.prompt_template = PromptTemplate(
            template= load_rag_summarize_prompt(),
            input_variables=["user_input", "context"]
        )
        self.model = chat_model
        self.chain = self._init_chain()

    def _init_chain(self):
        return self.prompt_template | self.model | StrOutputParser()

    def retriever_docs(self, query:str) -> list[Document]:
        return self.retriever.invoke(query)

    def rag_summarize(self, query:str) -> str:
        docs = self.retriever_docs(query)
        context = ""
        i = 0
        for doc in docs:
            i += 1
            context += f"【参考资料{i}】:内容:{doc.page_content} | 元数据:{doc.metadata}\n"

        return self.chain.invoke(
            {
                "user_input": query,
                "context": context
            }
        )

if __name__ == "__main__":
    service = RagSummarizeService()
    print(service.rag_summarize("给我总结一下，基于PCN的那篇论文，讲了些什么"))