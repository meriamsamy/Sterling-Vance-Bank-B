from collections import deque
from typing import Callable, Dict, List, Optional, Union

try:
    # Optional: only needed to recognize LangChain message objects.
    # client.py passes the list returned by agent.ainvoke()["messages"],
    # which contains BaseMessage subclasses, not plain dicts.
    from langchain_core.messages import BaseMessage
except ImportError:  # pragma: no cover
    BaseMessage = None

# LangChain's internal role names ("human"/"ai") don't match the role
# names used everywhere else in this codebase ("user"/"assistant").
_LC_ROLE_MAP = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "tool",
}


class ShortTermMemory:
    """
    Rolling short-term memory for the banking agent.

    Architectural rules (issue #40's overflow contract):
    - Stores only the recent conversation transcript. The scratchpad
      (memory/short_term_memory/scratchpad.py) is separate and is NOT
      stored here.
    - NEVER silently evicts messages. A bounded deque(maxlen=...) would
      drop the oldest message before the Promote-or-Drop Router could
      ever see it - that silent-eviction bug is exactly what this
      class is written to avoid.
    - When the buffer is full, overflow MUST be processed explicitly
      through the Promote-or-Drop Router (add_message_with_routing)
      before the oldest message is removed.
    - This class never writes to episodic or semantic memory itself -
      it only ever hands aging messages to whatever route_fn the
      caller supplies.
    """

    def __init__(self, max_messages: int = 20):
        if max_messages <= 0:
            raise ValueError("max_messages must be greater than 0")

        self.max_messages = max_messages

        # IMPORTANT: no maxlen here - see class docstring.
        self.messages = deque()

    # ============================================================
    # NORMALIZATION
    # ============================================================

    @staticmethod
    def _normalize(msg: Union[Dict, "BaseMessage"]) -> Dict:
        """
        Convert a message of unknown shape (plain dict or LangChain
        BaseMessage) into the plain {"role", "content", ...} dict
        format used throughout short-term memory, the context
        strategies, and the promote-or-drop router.
        """
        if BaseMessage is not None and isinstance(msg, BaseMessage):
            role = _LC_ROLE_MAP.get(msg.type, msg.type)
            content = msg.content

            if not isinstance(content, str):
                if isinstance(content, list):
                    content = "".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                else:
                    content = str(content)

            normalized = {"role": role, "content": content}

            # ToolMessage REQUIRES tool_call_id to be reconstructed by
            # LangChain later - dropping it causes a KeyError the next
            # time this stored message is fed back into agent.ainvoke().
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id is not None:
                normalized["tool_call_id"] = tool_call_id

            # An AIMessage that requested a tool call carries tool_calls.
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                normalized["tool_calls"] = tool_calls

            name = getattr(msg, "name", None)
            if name is not None:
                normalized["name"] = name

            return normalized

        if isinstance(msg, dict):
            # Keep every field already present (role/content and,
            # if this dict already went through _normalize before,
            # tool_call_id/tool_calls too).
            return dict(msg)

        # Last-resort fallback so a stray/unexpected type never
        # crashes the pipeline - surfaces as visible text instead.
        return {"role": "unknown", "content": str(msg)}

    # ============================================================
    # BASIC OPERATIONS
    # ============================================================

    def add_message(self, role: str, content: str) -> bool:
        """
        Add a message only if there is available capacity.

        This method NEVER evicts an existing message. Returns True if
        the message was added, False if short-term memory is full
        (in which case the caller must use add_message_with_routing
        instead - or handle overflow itself first).
        """
        if self.is_full():
            return False

        self.messages.append({"role": role, "content": content})
        return True

    def add_message_with_routing(
        self,
        role: str,
        content: str,
        route_fn: Optional[Callable[[List[Dict]], None]] = None,
    ) -> bool:
        """
        Add a plain {"role", "content"} message while enforcing the
        Promote-or-Drop overflow rule. For messages that need to keep
        LangChain-specific fields (ToolMessage's tool_call_id, an
        AIMessage's tool_calls), use
        add_normalized_message_with_routing instead - this method is
        for messages the caller is typing directly (e.g. the user's
        own input), which never carry those fields.
        """
        return self.add_normalized_message_with_routing(
            {"role": role, "content": content}, route_fn
        )

    def add_normalized_message_with_routing(
        self,
        normalized_message: Dict,
        route_fn: Optional[Callable[[List[Dict]], None]] = None,
    ) -> bool:
        """
        Add an already-normalized message dict while enforcing the
        Promote-or-Drop overflow rule. Unlike add_message_with_routing,
        this stores the dict as-is, so tool_call_id / tool_calls / name
        (added by _normalize() for LangChain messages) survive - losing
        them would break reconstructing a ToolMessage on a later turn.

        If short-term memory is full:
          1. identify the oldest message (overflow_candidates())
          2. hand it to route_fn (the Promote-or-Drop Router) BEFORE
             removing anything
          3. only then remove the oldest message
          4. append the new message

        route_fn receives the aging message(s) as a list of dicts and
        is responsible for deciding forget vs. promote-to-episodic. It
        must never write directly to semantic memory - that boundary
        is enforced by promote_or_drop_router.py, not here.
        """
        if self.is_full():
            candidates = self.overflow_candidates()

            if route_fn is None:
                raise RuntimeError(
                    "Short-term memory overflow requires an explicit "
                    "Promote-or-Drop Router (route_fn). Silent "
                    "eviction is disabled."
                )

            # Route BEFORE removing anything - only safe to evict
            # once the router has actually seen the message.
            route_fn(candidates)
            self.remove_oldest()

        self.messages.append(dict(normalized_message))
        return True

    # ============================================================
    # READING MEMORY
    # ============================================================

    def get_messages(self) -> List[Dict]:
        return list(self.messages)

    def export(self) -> List[Dict]:
        return list(self.messages)

    # ============================================================
    # REPLACE MEMORY
    # ============================================================

    def replace_messages(self, messages: List[Union[Dict, "BaseMessage"]]):
        """
        Replace the current transcript with the latest conversation
        returned by the agent. All messages are normalized before
        storage.

        This method NEVER silently prunes messages: if the supplied
        conversation is larger than max_messages, it raises
        ValueError so the caller is forced to explicitly route the
        overflow through the Promote-or-Drop Router first (see
        client.py's STEP 11 for the required pattern).
        """
        normalized = [self._normalize(message) for message in messages]

        if len(normalized) > self.max_messages:
            raise ValueError(
                f"replace_messages received {len(normalized)} messages, "
                f"but max_messages={self.max_messages}. Route the "
                "overflow through the Promote-or-Drop Router before "
                "replacing short-term memory."
            )

        self.messages = deque(normalized)

    # ============================================================
    # REMOVE / CLEAR
    # ============================================================

    def remove_oldest(self):
        """
        Remove the oldest message. Should only ever be called after
        that message has already been processed by the
        Promote-or-Drop Router (see add_message_with_routing).
        """
        if self.messages:
            return self.messages.popleft()
        return None

    def clear(self):
        self.messages.clear()

    # ============================================================
    # OVERFLOW / PROMOTE-OR-DROP
    # ============================================================

    def overflow_candidates(self) -> List[Dict]:
        """
        Return the message that will age out the next time short-term
        memory needs room. This method NEVER removes anything - it's
        a read-only hook for the Promote-or-Drop Router.

        For a rolling window with one-message-at-a-time insertion,
        this is the oldest message only.
        """
        if not self.messages:
            return []
        return [dict(self.messages[0])]

    # ============================================================
    # INSPECTION
    # ============================================================

    def peek_oldest(self):
        if self.messages:
            return self.messages[0]
        return None

    def peek_latest(self):
        if self.messages:
            return self.messages[-1]
        return None

    def oldest_message(self):
        if not self.messages:
            return None
        return self.messages[0]

    def newest_message(self):
        if not self.messages:
            return None
        return self.messages[-1]

    # ============================================================
    # SIZE / STATUS
    # ============================================================

    def count(self) -> int:
        return len(self.messages)

    def size(self) -> int:
        return len(self.messages)

    def is_full(self) -> bool:
        return len(self.messages) >= self.max_messages