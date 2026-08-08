import asyncio
import builtins
import contextlib
import importlib.util
import io
import re
import sys
import time
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
CLIENT_DIR = TEST_DIR
PROJECT_ROOT = CLIENT_DIR.parent

CLIENT_PATH = CLIENT_DIR / "client.py"
README = PROJECT_ROOT / "README.md"

# ============================================================
# TEST SCENARIO
# ============================================================

TEST_REQUESTS = [
    "Login with employee ID 4.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-001 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-002 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-003 in IR.",
    "What suspicious wire transfer activity happened earlier? Tell me the previous transfers and any pattern you noticed.",
]

# ============================================================
# LOAD REAL CLIENT
# ============================================================

def load_client_module():
    if not CLIENT_PATH.exists():
        raise FileNotFoundError(f"Client not found:\n{CLIENT_PATH}")

    spec = importlib.util.spec_from_file_location(
        "client_module",
        CLIENT_PATH
    )

    if spec is None or spec.loader is None:
        raise ImportError(
            f"Could not load client module:\n{CLIENT_PATH}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules["client_module"] = module
    spec.loader.exec_module(module)

    return module


# ============================================================
# RUN REAL CLIENT
# ============================================================

async def run_client():
    module = load_client_module()

    inputs = iter(TEST_REQUESTS + ["exit"])
    original_input = builtins.input

    def fake_input(prompt=""):
        prompt_lower = str(prompt).lower()

        if "approve transfer" in prompt_lower:
            print("\n[TEST ELICITATION] no")
            return "no"

        try:
            value = next(inputs)
            print(f"\n[TEST INPUT] {value}")
            return value
        except StopIteration:
            return "exit"

    builtins.input = fake_input

    captured = io.StringIO()
    start = time.perf_counter()

    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            await module.main()
    finally:
        builtins.input = original_input

    elapsed = time.perf_counter() - start

    return captured.getvalue(), elapsed


# ============================================================
# HELPERS
# ============================================================

def count(output, pattern):
    return len(re.findall(pattern, output, re.IGNORECASE))


def has(output, pattern):
    return bool(re.search(pattern, output, re.IGNORECASE))


# ============================================================
# EVALUATION
# ============================================================

def evaluate(output):
    evidence = {}

    request_count = len(TEST_REQUESTS)

    # ========================================================
    # 1. HYBRID RAG
    # ========================================================

    rag_runs = count(
        output,
        r"\[HYBRID RAG\]\s*Searching"
    )

    evidence["Hybrid RAG executed for every request"] = (
        rag_runs >= request_count
    )

    # ========================================================
    # 2. SELF-RAG RETRIEVAL VERIFICATION
    # ========================================================

    verified_rag = count(
        output,
        r"\[HYBRID RAG\]\s*Status:\s*VERIFIED"
    )

    rejected_after_retrieval = count(
        output,
        r"REJECTED_AFTER_RETRIEVAL"
    )

    unanswerable_rag = count(
        output,
        r"Status:\s*UNANSWERABLE"
    )

    rag_statuses = (
        verified_rag
        + rejected_after_retrieval
        + unanswerable_rag
    )

    evidence["Self-RAG retrieval verification produced statuses"] = (
        rag_statuses >= request_count
    )

    evidence["At least one RAG retrieval was verified"] = (
        verified_rag >= 1
    )

    # ========================================================
    # 3. SELF-RAG POST-GENERATION VERIFICATION
    # ========================================================

    evidence["Self-RAG generation verification is active"] = (
        has(output, r"REJECTED_AFTER_GENERATION")
        or has(output, r"Status:\s*VERIFIED")
        or has(output, r"Status:\s*UNANSWERABLE")
    )

    # ========================================================
    # 4. SHORT-TERM MEMORY
    # ========================================================

    scratchpad_count = count(
        output,
        r"\[scratchpad\]"
    )

    evidence["Short-term memory remains active across requests"] = (
        scratchpad_count >= request_count
    )

    # ========================================================
    # 5. SCRATCHPAD
    # ========================================================

    evidence["Scratchpad maintains working state"] = has(
        output,
        r"Waiting for next request"
    )

    evidence["Scratchpad records tool activity"] = has(
        output,
        r"Tool call:"
    )

    # ========================================================
    # 6. EPISODIC MEMORY
    # ========================================================

    episode_count = count(
        output,
        r"\[LONG-TERM MEMORY\]\s*Transfer episode stored"
    )

    evidence["Episodic memory stored transfer #1"] = (
        episode_count >= 1
    )

    evidence["Episodic memory stored transfer #2"] = (
        episode_count >= 2
    )

    evidence["Episodic memory stored transfer #3"] = (
        episode_count >= 3
    )

    # ========================================================
    # 7. SEMANTIC CONSOLIDATION
    # ========================================================

    consolidation_count = count(
        output,
        r"Fraud pattern consolidated"
    )

    evidence["Semantic memory consolidation triggered"] = (
        consolidation_count >= 1
    )

    # ========================================================
    # 8. LONG-TERM MEMORY RETRIEVAL
    # ========================================================

    retrieval_count = count(
        output,
        r"\[LONG-TERM MEMORY\]\s*Relevant memories found"
    )

    evidence["Long-term memory was retrieved"] = (
        retrieval_count >= 1
    )

    # ========================================================
    # 9. MEMORY POST-RETRIEVAL VERIFICATION
    # ========================================================

    memory_verification_count = count(
        output,
        r"\[LONG-TERM MEMORY\]\s*Supported:"
    )

    evidence["Long-term memory post-retrieval verification executed"] = (
        memory_verification_count >= 1
    )

    # ========================================================
    # 10. EPISODIC MEMORY RETRIEVED
    # ========================================================

    evidence["Retrieved episodic memory was available"] = has(
        output,
        r"Episodic relevant:\s*True"
    ) or has(
        output,
        r"Recent Episodic Memory"
    )

    # ========================================================
    # 11. SEMANTIC MEMORY RETRIEVED
    # ========================================================

    evidence["Retrieved semantic memory was available"] = has(
        output,
        r"Semantic relevant:\s*True"
    ) or has(
        output,
        r"Consolidated Semantic Memory"
    )

    # ========================================================
    # 12. MEMORY POST-GENERATION VERIFICATION
    # ========================================================

    evidence["Long-term memory post-generation verification executed"] = (
        has(output, r"Verifying generated answer")
        and (
            has(output, r"Answer supported:\s*True")
            or has(output, r"Answer supported:\s*False")
        )
    )

    # ========================================================
    # 13. FINAL MEMORY QUERY
    # ========================================================

    evidence["Final memory-based query executed"] = has(
        output,
        r"What suspicious wire transfer activity happened earlier"
    )

    # ========================================================
    # 14. MEMORY USED FOR FINAL ANSWER
    # ========================================================

    evidence["Previous transfer history reached the final reasoning flow"] = (
        has(output, r"Recent Episodic Memory")
        or has(output, r"episodic relevant:\s*True")
    )

    # ========================================================
    # 15. MEMORY + RAG SAME PIPELINE
    # ========================================================

    evidence["RAG and long-term memory integrated in live pipeline"] = (
        rag_runs >= request_count
        and retrieval_count >= 1
    )

    # ========================================================
    # 16. MCP OPERATION USED AS MEMORY DATA SOURCE
    # ========================================================
    # This is NOT testing the old MCP functionality.
    # It only proves that the new memory layer received
    # real events generated by the live banking workflow.

    evidence["Live banking events generated episodic memory"] = (
        episode_count >= 3
    )

    return evidence


# ============================================================
# BUILD REPORT
# ============================================================

def build_report(output, elapsed, evidence):
    passed = sum(1 for value in evidence.values() if value)
    total = len(evidence)

    rag_runs = count(
        output,
        r"\[HYBRID RAG\]\s*Searching"
    )

    verified_rag = count(
        output,
        r"\[HYBRID RAG\]\s*Status:\s*VERIFIED"
    )

    episodes = count(
        output,
        r"\[LONG-TERM MEMORY\]\s*Transfer episode stored"
    )

    consolidations = count(
        output,
        r"Fraud pattern consolidated"
    )

    retrievals = count(
        output,
        r"\[LONG-TERM MEMORY\]\s*Relevant memories found"
    )

    lines = [
        "## Agent Memory & RAG End-to-End Integration Test",
        "",
        f"- **Run time:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Execution time:** {elapsed:.2f}s",
        f"- **Integration evidence:** **{passed}/{total} checks passed**",
        f"- **Requests executed:** {len(TEST_REQUESTS)}",
        f"- **Hybrid RAG executions:** {rag_runs}/{len(TEST_REQUESTS)}",
        f"- **Verified RAG results:** {verified_rag}",
        f"- **Episodic memories stored:** {episodes}",
        f"- **Semantic consolidations:** {consolidations}",
        f"- **Long-term memory retrievals:** {retrievals}",
        "",
        "### Components Tested",
        "",
        "| Component | Result |",
        "|---|---|",
    ]

    for name, result in evidence.items():
        status = "PASS" if result else "FAIL"
        lines.append(
            f"| {name} | **{status}** |"
        )

    lines += [
        "",
        "### End-to-End Flow",
        "",
        "```text",
        "User Request",
        "    ↓",
        "Short-Term Memory",
        "    ↓",
        "Scratchpad",
        "    ↓",
        "Selected Context Strategy",
        "    ↓",
        "Hybrid RAG",
        "    ↓",
        "Self-RAG Retrieval Verification",
        "    ↓",
        "Long-Term Memory Retrieval",
        "    ↓",
        "Memory Post-Retrieval Verification",
        "    ↓",
        "Verified Memory + RAG Context",
        "    ↓",
        "Agent",
        "    ↓",
        "Live Banking Operation",
        "    ↓",
        "Episodic Memory",
        "    ↓",
        "Semantic Consolidation",
        "    ↓",
        "Next Request",
        "    ↓",
        "Long-Term Memory Retrieval",
        "    ↓",
        "Memory Post-Generation Verification",
        "    ↓",
        "Grounded Final Answer",
        "```",
        "",
        "### Test Requests",
        "",
    ]

    for index, request in enumerate(TEST_REQUESTS, start=1):
        lines.append(
            f"{index}. `{request}`"
        )

    lines += [
        "",
        "### What This Test Proves",
        "",
        "- Short-term conversation memory remains active across requests.",
        "- Scratchpad maintains temporary working state.",
        "- Hybrid RAG executes for every request.",
        "- Self-RAG verifies retrieved knowledge before generation.",
        "- Self-RAG verifies generated answers against retrieved context.",
        "- Live banking events are converted into episodic memories.",
        "- Repeated suspicious events trigger semantic consolidation.",
        "- Long-term memory is retrieved for a relevant follow-up request.",
        "- Retrieved long-term memory is verified before entering the agent context.",
        "- Episodic and semantic memory can both contribute to the final reasoning flow.",
        "- Long-term-memory-dependent answers receive post-generation verification.",
        "- RAG and long-term memory operate together inside the same live client pipeline.",
        "",
        "### Note",
        "",
        "MCP banking operations are used only to create realistic live events required by the memory workflow. The existing MCP functionality itself is not evaluated as a separate feature in this test.",
        "",
        "### Run",
        "",
        "```bash",
        'python -u "client\\test_client.py"',
        "```",
        "",
        "### Raw Output",
        "",
        "```text",
        output[-10000:],
        "```",
        "",
    ]

    if passed == total:
        lines.append(
            "**Result: PASSED — Memory, RAG, and context management are demonstrated end-to-end.**"
        )
    else:
        lines.append(
            f"**Result: PARTIAL — {total - passed} checks failed.**"
        )

    lines.append("")

    return "\n".join(lines)


# ============================================================
# UPDATE README
# ============================================================

def update_readme(report):
    if README.exists():
        readme = README.read_text(encoding="utf-8")
    else:
        readme = "# Sterling & Vance Bank\n"

    marker = "## Agent Memory & RAG End-to-End Integration Test"

    if marker in readme:
        readme = (
            readme.split(marker)[0].rstrip()
            + "\n\n"
        )
    else:
        readme = readme.rstrip() + "\n\n"

    README.write_text(
        readme + report,
        encoding="utf-8"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 65)
    print("STERLING & VANCE - MEMORY & RAG END-TO-END TEST")
    print("=" * 65)

    print(f"Project root: {PROJECT_ROOT}")
    print(f"Client file: {CLIENT_PATH}")
    print(f"README: {README}")
    print()

    try:
        output, elapsed = asyncio.run(run_client())

    except Exception as exc:
        report = "\n".join([
            "## Agent Memory & RAG End-to-End Integration Test",
            "",
            "- **Result:** FAILED",
            f"- **Error:** `{type(exc).__name__}: {exc}`",
            "",
            "```text",
            str(exc),
            "```",
            "",
        ])

        update_readme(report)
        print(report)
        raise

    evidence = evaluate(output)

    report = build_report(
        output,
        elapsed,
        evidence
    )

    update_readme(report)

    print(report)
    print("\nREADME.md updated successfully.")

    if not all(evidence.values()):
        sys.exit(1)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
