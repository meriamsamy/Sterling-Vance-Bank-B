import os
import time
from typing import Dict, List
import tiktoken

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq

from memory.context_strategies.context_manager import ContextManager


class ContextEvaluator:

    def __init__(self, model_name: str = "gpt-4o"):
        self.manager = ContextManager()
        self.tokenizer = tiktoken.encoding_for_model(model_name)

        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="openai/gpt-oss-20b",
            temperature=0.1,
        )

    def count_tokens(self, messages: List[Dict]) -> int:
        """Calculate total token count across all messages in the payload."""
        total_tokens = 0
        for msg in messages:
            content = str(msg.get("content", ""))
            total_tokens += len(self.tokenizer.encode(content))
        return total_tokens

    def _sanitize_for_llm(self, messages: List[Dict]) -> List[Dict]:
        """Convert role='tool' messages into assistant-visible context."""
        sanitized = []
        for m in messages:
            role = m.get("role")
            content = str(m.get("content", ""))
            if role == "tool":
                sanitized.append({
                    "role": "assistant",
                    "content": f"[Previous tool result]\n{content}",
                })
            elif role in ("user", "assistant", "system"):
                sanitized.append({"role": role, "content": content})
            else:
                sanitized.append({"role": "assistant", "content": content})
        return sanitized

    def evaluate_accuracy(self, processed_messages: List[Dict], needle_key: str) -> bool:
        """Check if needle survived in the pruned context."""
        full_text = " ".join([str(m.get("content", "")) for m in processed_messages])
        return needle_key.lower() in full_text.lower()

    def run_multi_needle_benchmark(
        self, base_messages: List[Dict], test_cases: List[Dict]
    ) -> List[Dict]:
        """Run evaluation over multiple needles to compute an accuracy percentage."""
        strategies = ["sliding", "masking", "summary", "zone"]
        benchmark_results = []

        print("\n=== Running Multi-Needle Context Window Evaluation ===\n")

        for strat_name in strategies:
            successful_recalls = 0
            total_latency = 0.0
            total_input_tokens = 0

            for case in test_cases:
                needle = case["needle"]
                
                # إدخال الـ Needle الخاصة بكل اختبار في المحادثة
                messages_copy = [dict(m) for m in base_messages]
                messages_copy[3] = {
                    "role": "user",
                    "content": f"My verification {case['type']} is {needle}.",
                }

                # 1. قياس زمن المعالجة (Latency)
                start_time = time.perf_counter()
                processed_msgs = self.manager.process(strat_name, messages_copy)
                total_latency += (time.perf_counter() - start_time)

                # 2. قياس التوكنز في المدخلات
                total_input_tokens += self.count_tokens(processed_msgs)

                # 3. تقييم بقاء المعلومة في الكونتكست
                if self.evaluate_accuracy(processed_msgs, needle):
                    successful_recalls += 1

            total_runs = len(test_cases)
            accuracy_pct = (successful_recalls / total_runs) * 100
            avg_latency_ms = (total_latency / total_runs) * 1000
            avg_input_tokens = round(total_input_tokens / total_runs)

            benchmark_results.append({
                "Strategy": strat_name,
                "Avg Input Tokens": avg_input_tokens,
                "Avg Latency (ms)": round(avg_latency_ms, 2),
                "Accuracy (%)": f"{accuracy_pct:.1f}%",
            })

        self._print_results_table(benchmark_results)
        return benchmark_results

    def _print_results_table(self, results: List[Dict]):
        """Print formatted results table."""
        header = f"{'Strategy':<12} | {'In Tokens':<10} | {'Latency (ms)':<14} | {'Accuracy (%)':<12}"
        print(header)
        print("-" * len(header))
        for res in results:
            print(
                f"{res['Strategy']:<12} | {res['Avg Input Tokens']:<10} | "
                f"{res['Avg Latency (ms)']:<14} | {res['Accuracy (%)']:<12}"
            )
        print("-" * len(header))


if __name__ == "__main__":
    # المحادثة الرئيسية (Haystack)
    test_messages = [
        {"role": "system", "content": "You are a helpful banking agent."},
        {"role": "user", "content": "Hello, I want to open an account."},
        {"role": "assistant", "content": "Sure! I can help you with that."},
        {"role": "user", "content": "My secret verification PIN code is 9876."},
        {"role": "tool", "content": "KYC lookup result: " + "X" * 1200},
        {"role": "assistant", "content": "Thanks, verified. What would you like to do?"},
        {"role": "user", "content": "Show me my last 5 transactions."},
        {"role": "tool", "content": "Transaction history dump: " + "Y" * 1500},
        {"role": "assistant", "content": "Here are your last 5 transactions."},
        {"role": "user", "content": "Can I transfer 500 dollars?"},
        {"role": "assistant", "content": "Sure, to which account?"},
        {"role": "user", "content": "Account number is 123456789."},
        {"role": "tool", "content": "Account validation result: " + "Z" * 1300},
        {"role": "assistant", "content": "Account validated. Confirm the transfer?"},
        {"role": "user", "content": "Yes, confirmed."},
        {"role": "tool", "content": "Transfer engine log: " + "A" * 1400},
        {"role": "assistant", "content": "Processing the request now..."},
        {"role": "user", "content": "Did it go through?"},
        {"role": "tool", "content": "Settlement status dump: " + "B" * 1200},
        {"role": "assistant", "content": "Yes, successfully transferred."},
        {"role": "user", "content": "What's my current balance?"},
        {"role": "tool", "content": "Balance service response: " + "C" * 1300},
        {"role": "assistant", "content": "Your current balance is $2,450."},
        {"role": "user", "content": "Can you also check my savings account?"},
        {"role": "tool", "content": "Savings account dump: " + "D" * 1400},
        {"role": "assistant", "content": "Your savings balance is $10,000."},
        {"role": "user", "content": "Great, one more transfer of $200 please."},
        {"role": "tool", "content": "Second transfer engine log: " + "E" * 1200},
        {"role": "assistant", "content": "Done, $200 transferred."},
        {"role": "user", "content": "Thanks, that's all for now."},
        {"role": "user", "content": "Wait, one last thing - can you confirm my details once more?"},
    ]

    # حالات الاختبار المتعددة (Needles)
    test_cases = [
        {"needle": "9876", "type": "PIN code"},
        {"needle": "ACC-55412", "type": "Account Number"},
        {"needle": "CONF-8820", "type": "Confirmation Code"},
        {"needle": "USD 4,500", "type": "Transfer Amount"},
        {"needle": "Alexandria", "type": "Branch Name"},
    ]

    evaluator = ContextEvaluator()
    evaluator.run_multi_needle_benchmark(test_messages, test_cases)