from .sliding_window import SlidingWindowStrategy
from .observation_masking import ObservationMaskingStrategy
from .recursive_summarization import RecursiveSummarizationStrategy
from .zone_based_pruning import ZoneBasedPruningStrategy


class ContextManager:

    def __init__(self):

        self.strategies = {

            "sliding": SlidingWindowStrategy(),

            "masking": ObservationMaskingStrategy(),

            "summary": RecursiveSummarizationStrategy(),

            "zone": ZoneBasedPruningStrategy(),
        }

    def process(self, strategy_name, messages):

        strategy = self.strategies[strategy_name]

        return strategy.apply(messages)