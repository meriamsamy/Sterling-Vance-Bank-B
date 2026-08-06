from typing import List, Dict

from .recursive_summarization import RecursiveSummarizationStrategy
from .observation_masking import ObservationMaskingStrategy


class ZoneBasedPruningStrategy:
    """
    Divide the conversation into three zones:

    Zone 1 (Old): Summarize
    Zone 2 (Middle): Mask large tool outputs
    Zone 3 (Recent): Keep unchanged
    """

    def __init__(self):
        self.summarizer = RecursiveSummarizationStrategy()
        self.masker = ObservationMaskingStrategy()

    def apply(self, messages: List[Dict]) -> List[Dict]:

        if len(messages) <= 9:
            return messages

        n = len(messages)

        first_end = n // 3
        second_end = 2 * n // 3

        zone1 = messages[:first_end]
        zone2 = messages[first_end:second_end]
        zone3 = messages[second_end:]

        # Old messages → summarize
        zone1 = self.summarizer.apply(zone1)

        # Middle messages → mask tool outputs
        zone2 = self.masker.apply(zone2)

        # Recent messages → keep as-is
        return zone1 + zone2 + zone3