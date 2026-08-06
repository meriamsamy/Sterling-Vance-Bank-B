from typing import List, Dict


class SlidingWindowStrategy:
    """
    Keeps only the most recent N messages and drops everything older.
    Simplest and cheapest strategy, but has no memory of anything
    outside the window.
    """

    def __init__(self, window_size: int = 10, keep_system: bool = True):
        self.window_size = window_size
        self.keep_system = keep_system

    def apply(self, messages: List[Dict]) -> List[Dict]:

        if len(messages) <= self.window_size:
            return messages

        if not self.keep_system:
            return messages[-self.window_size:]

        # Keep any leading system/reference messages (e.g. the seeded
        # wire transfer policy) so the sliding window doesn't silently
        # drop the policy context along with old chat turns.
        system_messages = [
            msg for msg in messages if msg.get("role") == "system"
        ]

        recent_messages = messages[-self.window_size:]

        # Avoid duplicating a system message that already falls inside
        # the recent window.
        recent_ids = {id(msg) for msg in recent_messages}
        leading_system = [
            msg for msg in system_messages if id(msg) not in recent_ids
        ]

        return leading_system + recent_messages