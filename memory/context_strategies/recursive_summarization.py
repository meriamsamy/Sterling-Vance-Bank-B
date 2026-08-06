from typing import List, Dict
import os

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage


class RecursiveSummarizationStrategy:
    """
    Summarizes older messages using an LLM while keeping
    the most recent messages unchanged.
    """

    def __init__(self, threshold: int = 15, keep_recent: int = 8):
        self.threshold = threshold
        self.keep_recent = keep_recent

        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="openai/gpt-oss-20b",
            temperature=0.3,
        )

    def _summarize_text(self, text_to_summarize: str) -> str:
        """
        Send old conversation to the LLM and receive a summary.
        """

        prompt = f"""
You are a banking memory summarization assistant.

Summarize the following conversation while preserving only important information such as:
- Customer identity
- Account information
- Decisions made
- Current banking request
- Important warnings
- Compliance-related information

Ignore greetings, repeated confirmations, and unnecessary conversation.

Conversation:

{text_to_summarize}
"""

        response = self.llm.invoke(
            [HumanMessage(content=prompt)]
        )

        return response.content

    def apply(self, messages: List[Dict]) -> List[Dict]:

        if len(messages) <= self.threshold:
            return messages

        old_messages = messages[:-self.keep_recent]
        recent_messages = messages[-self.keep_recent:]

        text_to_summarize = "\n".join(
            f"{msg.get('role')}: {msg.get('content')}"
            for msg in old_messages
        )

        summary = self._summarize_text(text_to_summarize)

        summary_message = {
            "role": "system",
            "content": f"[Conversation Summary]\n{summary}"
        }

        return [summary_message] + recent_messages