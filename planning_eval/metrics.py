from langchain_core.callbacks import BaseCallbackHandler


class MetricsTracker(BaseCallbackHandler):

    def __init__(self):
        self.reset()

    def reset(self):
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0

    def on_llm_end(self, response, **kwargs):
        self.llm_calls += 1

        usage = {}

        if getattr(response, "llm_output", None):
            usage = (
                response.llm_output.get(
                    "token_usage",
                    {},
                )
                or {}
            )

        if not usage and getattr(
            response,
            "generations",
            None,
        ):
            try:
                message = (
                    response.generations[0][0].message
                )

                usage = (
                    getattr(
                        message,
                        "usage_metadata",
                        {},
                    )
                    or {}
                )

            except (
                AttributeError,
                IndexError,
            ):
                pass

        self.input_tokens += (
            usage.get(
                "input_tokens",
                usage.get("prompt_tokens", 0),
            )
            or 0
        )

        self.output_tokens += (
            usage.get(
                "output_tokens",
                usage.get("completion_tokens", 0),
            )
            or 0
        )

        self.total_tokens += (
            usage.get(
                "total_tokens",
                0,
            )
            or 0
        )

    def snapshot(self):
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }