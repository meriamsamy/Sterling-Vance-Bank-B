from collections import deque
from typing import Dict, List, Union

try:
    # Optional: only needed to recognize LangChain message objects.
    # The agent (client.py) returns BaseMessage subclasses
    # (HumanMessage/AIMessage/ToolMessage/SystemMessage) from
    # agent.ainvoke(), not plain dicts, so ShortTermMemory has to be
    # able to normalize both shapes into the same plain-dict format
    # that the context strategies (sliding/masking/summary/zone) expect.
    from langchain_core.messages import BaseMessage
except ImportError:  # pragma: no cover
    BaseMessage = None

# LangChain's internal role names ("human"/"ai") don't match the
# role names used everywhere else in this codebase ("user"/"assistant").
_LC_ROLE_MAP = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "tool",
}


class ShortTermMemory:
    """
    Rolling short-term memory for the banking agent.
    Stores only the latest N messages.
    Long-term promotion is handled by another component.

    Always stores plain {"role": ..., "content": ...} dicts internally,
    regardless of whether callers pass dicts or LangChain BaseMessage
    objects (e.g. the list returned by agent.ainvoke()["messages"]).
    """

    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        self.messages = deque(maxlen=max_messages)

    @staticmethod
    def _normalize(msg: Union[Dict, "BaseMessage"]) -> Dict:
        """
        Convert a message of unknown shape (plain dict or LangChain
        BaseMessage) into the plain dict format used throughout
        short-term memory and the context strategies.
        """
        if BaseMessage is not None and isinstance(msg, BaseMessage):
            role = _LC_ROLE_MAP.get(msg.type, msg.type)
            content = msg.content
            if not isinstance(content, str):
                # Newer LangChain content can be a list of content
                # blocks (tool calls, multimodal parts, etc.) instead
                # of a plain string - flatten it to text so downstream
                # token counting / substring checks never crash.
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                ) if isinstance(content, list) else str(content)

            normalized = {"role": role, "content": content}

            # ToolMessage REQUIRES tool_call_id to be reconstructed by
            # LangChain later. Dropping it here is exactly what causes:
            #   KeyError: 'tool_call_id'
            # the next time this stored message is fed back into
            # agent.ainvoke() on a later turn.
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id is not None:
                normalized["tool_call_id"] = tool_call_id

            # An AIMessage that requested a tool call carries tool_calls.
            # Keep it so the ToolMessage that follows still points back
            # to a real tool call instead of becoming orphaned.
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                normalized["tool_calls"] = tool_calls

            name = getattr(msg, "name", None)
            if name is not None:
                normalized["name"] = name

            return normalized

        if isinstance(msg, dict):
            # Keep every field already present - role/content, and, if
            # this dict already went through _normalize() before,
            # tool_call_id / tool_calls too. Stripping down to just
            # role/content here would silently reintroduce the same
            # KeyError on the next agent call.
            return dict(msg)

        # Last-resort fallback so a stray/unexpected type never crashes
        # the whole pipeline - surfaces as visible text instead.
        return {"role": "unknown", "content": str(msg)}

    def add_message(self, role: str, content: str):
        """
        Add a new message to short-term memory.
        """

        self.messages.append({
            "role": role,
            "content": content
        })

    def get_messages(self) -> List[Dict]:
        """
        Return all current messages.
        """
        return list(self.messages)

    def replace_messages(self, messages: List[Union[Dict, "BaseMessage"]]):
        """
        Replace memory with updated conversation returned by the agent.
        Accepts either plain dicts or LangChain BaseMessage objects and
        normalizes everything to plain dicts before storing, so every
        downstream consumer (context strategies, token counting, the
        promote-or-drop router) can rely on a single consistent shape.
        """

        self.messages = deque(
            (self._normalize(m) for m in messages),
            maxlen=self.max_messages
        )

    def clear(self):
        """
        Remove all messages.
        """
        self.messages.clear()



    def remove_oldest(self):
        """
        Remove the oldest message from memory.
        """
        if self.messages:
            return self.messages.popleft()
        return None

    def peek_oldest(self):
        """
        Return the oldest message without removing it.
        """
        if self.messages:
            return self.messages[0]
        return None

    def peek_latest(self):
        """
        Return the newest message.
        """
        if self.messages:
            return self.messages[-1]
        return None

    def count(self):
        """
        Return the current number of messages.
        """
        return len(self.messages)

    def export(self):
        """
        Export messages as a normal list.
        """
        return list(self.messages)

    def size(self):
        return len(self.messages)

    def is_full(self):
        return len(self.messages) >= self.max_messages

    def oldest_message(self):
        if not self.messages:
            return None
        return self.messages[0]

    def newest_message(self):
        if not self.messages:
            return None
        return self.messages[-1]

    # -----------------------------
    # Hook for Task 2
    # -----------------------------
    def overflow_candidates(self):
        """
        Returns messages that would be evaluated by the
        Promote-or-Drop Router.

        Task 2 will implement the routing logic.
        """
        return list(self.messages)