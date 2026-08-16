from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


MODEL_PRICING = {
    "mistral-small-latest": {
        "input": 0.10,
        "output": 0.30,
    },
}


@dataclass(frozen=True)
class MetricsSnapshot:
    llm_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_seconds: float
    estimated_cost_usd: float

    @property
    def calls(self) -> int:
        return self.llm_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_seconds": self.latency_seconds,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


class MetricsTracker(BaseCallbackHandler):
    def __init__(
        self,
        model_name: str = "mistral-small-latest",
    ) -> None:
        self.model_name = model_name
        self.reset()

    def reset(self) -> None:
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self._start_time: float | None = None
        self._end_time: float | None = None

    def start_timer(self) -> None:
        self._start_time = time.perf_counter()
        self._end_time = None

    def stop_timer(self) -> None:
        self._end_time = time.perf_counter()

    @property
    def latency_seconds(self) -> float:
        if self._start_time is None:
            return 0.0

        end = (
            self._end_time
            if self._end_time is not None
            else time.perf_counter()
        )

        return end - self._start_time

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        self.llm_calls += 1

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        usage = self._extract_usage(response)

        self.input_tokens += usage["input_tokens"]
        self.output_tokens += usage["output_tokens"]
        self.total_tokens += usage["total_tokens"]

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, int]:
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0

        llm_output = getattr(response, "llm_output", None)

        if isinstance(llm_output, dict):
            usage = llm_output.get("token_usage")

            if isinstance(usage, dict):
                input_tokens = int(
                    usage.get("input_tokens")
                    or usage.get("prompt_tokens")
                    or 0
                )
                output_tokens = int(
                    usage.get("output_tokens")
                    or usage.get("completion_tokens")
                    or 0
                )
                total_tokens = int(
                    usage.get("total_tokens")
                    or 0
                )

        generations = getattr(response, "generations", None)

        if generations:
            for generation_group in generations:
                for generation in generation_group:
                    message = getattr(
                        generation,
                        "message",
                        None,
                    )

                    if message is None:
                        continue

                    usage_metadata = getattr(
                        message,
                        "usage_metadata",
                        None,
                    )

                    if isinstance(usage_metadata, dict):
                        input_tokens = max(
                            input_tokens,
                            int(
                                usage_metadata.get(
                                    "input_tokens"
                                )
                                or 0
                            ),
                        )
                        output_tokens = max(
                            output_tokens,
                            int(
                                usage_metadata.get(
                                    "output_tokens"
                                )
                                or 0
                            ),
                        )
                        total_tokens = max(
                            total_tokens,
                            int(
                                usage_metadata.get(
                                    "total_tokens"
                                )
                                or 0
                            ),
                        )

                    response_metadata = getattr(
                        message,
                        "response_metadata",
                        None,
                    )

                    if isinstance(response_metadata, dict):
                        token_usage = response_metadata.get(
                            "token_usage"
                        )

                        if isinstance(token_usage, dict):
                            input_tokens = max(
                                input_tokens,
                                int(
                                    token_usage.get(
                                        "prompt_tokens"
                                    )
                                    or token_usage.get(
                                        "input_tokens"
                                    )
                                    or 0
                                ),
                            )
                            output_tokens = max(
                                output_tokens,
                                int(
                                    token_usage.get(
                                        "completion_tokens"
                                    )
                                    or token_usage.get(
                                        "output_tokens"
                                    )
                                    or 0
                                ),
                            )
                            total_tokens = max(
                                total_tokens,
                                int(
                                    token_usage.get(
                                        "total_tokens"
                                    )
                                    or 0
                                ),
                            )

        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    def estimated_cost_usd(self) -> float:
        pricing = MODEL_PRICING.get(self.model_name)

        if pricing is None:
            return 0.0

        input_cost = (
            self.input_tokens
            / 1_000_000
            * pricing["input"]
        )

        output_cost = (
            self.output_tokens
            / 1_000_000
            * pricing["output"]
        )

        return input_cost + output_cost

    def snapshot(self) -> dict[str, Any]:
        snapshot = MetricsSnapshot(
            llm_calls=self.llm_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
            latency_seconds=round(
                self.latency_seconds,
                6,
            ),
            estimated_cost_usd=round(
                self.estimated_cost_usd(),
                6,
            ),
        )

        return snapshot.to_dict()


def average_metrics(
    results: list[dict[str, Any]],
) -> dict[str, float]:
    if not results:
        return {
            "avg_llm_calls": 0.0,
            "avg_input_tokens": 0.0,
            "avg_output_tokens": 0.0,
            "avg_total_tokens": 0.0,
            "avg_latency_seconds": 0.0,
            "avg_estimated_cost_usd": 0.0,
        }

    count = len(results)

    def metric(
        result: dict[str, Any],
        name: str,
    ) -> float:
        return float(
            result.get("metrics", {}).get(
                name,
                0.0,
            )
        )

    return {
        "avg_llm_calls": round(
            sum(
                metric(r, "llm_calls")
                for r in results
            ) / count,
            2,
        ),
        "avg_input_tokens": round(
            sum(
                metric(r, "input_tokens")
                for r in results
            ) / count,
            2,
        ),
        "avg_output_tokens": round(
            sum(
                metric(r, "output_tokens")
                for r in results
            ) / count,
            2,
        ),
        "avg_total_tokens": round(
            sum(
                metric(r, "total_tokens")
                for r in results
            ) / count,
            2,
        ),
        "avg_latency_seconds": round(
            sum(
                float(
                    r.get(
                        "latency_seconds",
                        0.0,
                    )
                )
                for r in results
            ) / count,
            4,
        ),
        "avg_estimated_cost_usd": round(
            sum(
                metric(
                    r,
                    "estimated_cost_usd",
                )
                for r in results
            ) / count,
            6,
        ),
    }


def calculate_success_rate(
    results: list[dict[str, Any]],
) -> float:
    if not results:
        return 0.0

    successful = sum(
        1
        for result in results
        if result.get("success") is True
    )

    return round(
        successful / len(results) * 100,
        2,
    )


def summarize_method(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task_success_percent": calculate_success_rate(
            results
        ),
        **average_metrics(results),
        "num_cases": len(results),
    }