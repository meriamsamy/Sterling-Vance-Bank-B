import time
import pandas as pd

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from rag.naive_rag import naive_rag
from rag.hybrid_rag import hybrid_rag
from rag.agentic_rag import agentic_rag
from config import API_KEY
from retrieval_eval.test_questions import TEST_QUESTIONS


MODELS = {
    "Naive RAG": naive_rag,
    "Hybrid RAG": hybrid_rag,
    "Agentic RAG": agentic_rag,
}


rows = []

for model_name, model in MODELS.items():

    for item in TEST_QUESTIONS:

        question = item["question"]
        expected = item["expected"]

        # -------- Full RAG latency --------
        start = time.perf_counter()

        result = model(question)

        latency = time.perf_counter() - start


        answer = result["answer"].lower()

        if item["category"] == "Multi-hop":
            correct = all(keyword.lower() in answer for keyword in expected)
        else:
            correct = any(
                keyword.lower() in answer
                for keyword in expected
            )


        rows.append({

            "Architecture": model_name,

            "Question ID": item["id"],

            "Category": item["category"],

            "Correct": correct,

            "Latency (s)": round(latency, 3),

            "Tokens": result.get("tokens", 0),

            "Documents": result.get("documents_used", 0),

            "Iterations": result.get("iterations", 1),

            "Status": result["status"]

        })


df = pd.DataFrame(rows)


summary = (
    df.groupby("Architecture")
    .agg(
        Accuracy=("Correct", "sum"),
        Total=("Correct", "count"),
        AvgTokens=("Tokens", "mean"),
        AvgLatency=("Latency (s)", "mean"),
    )
)


summary["Accuracy"] = (
    summary["Accuracy"].astype(str)
    + "/"
    + summary["Total"].astype(str)
)

summary = summary.drop(columns=["Total"])


summary["AvgTokens"] = (
    summary["AvgTokens"]
    .round(0)
    .astype(int)
)


summary["AvgLatency"] = (
    summary["AvgLatency"]
    .round(3)
)


print("\nDetailed Results\n")
print(df)


print("\nSummary\n")
print(summary)


with open(
    "retrieval_eval/results.md",
    "w",
    encoding="utf-8"
) as f:

    f.write("# Retrieval Evaluation Results\n\n")

    f.write("## Detailed Results\n\n")
    f.write(df.to_markdown(index=False))

    f.write("\n\n## Summary\n\n")
    f.write(summary.to_markdown())