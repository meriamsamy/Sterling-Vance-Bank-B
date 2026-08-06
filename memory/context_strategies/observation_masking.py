from typing import List, Dict


class ObservationMaskingStrategy:
    """
    Replaces large tool outputs with placeholders to reduce context size.
    """

    def __init__(self, max_length: int = 500):
        self.max_length = max_length

    def apply(self, messages: List[Dict]) -> List[Dict]:

        masked = []

        for msg in messages:

            new_msg = msg.copy()

            if (
                new_msg.get("role") == "tool"
                and len(str(new_msg.get("content", ""))) > self.max_length
            ):

                new_msg["content"] = "[Tool output hidden to save context window.]"

            masked.append(new_msg)

        return masked