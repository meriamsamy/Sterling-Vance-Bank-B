import asyncio
import builtins
import contextlib
import importlib.util
import io
import re
import sys
import time
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

TEST_DIR = Path(__file__).resolve().parent
CLIENT_DIR = TEST_DIR
PROJECT_ROOT = CLIENT_DIR.parent

CLIENT_PATH = CLIENT_DIR / "client.py"
README = PROJECT_ROOT / "README.md"

sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================
# TEST SCENARIO
# ============================================================
#
# The current client.py uses:
#
#     ShortTermMemory(max_messages=20)
#
# directly.
#
# Therefore this test does NOT rely on STM_MAX_MESSAGES.
# Instead, enough requests are executed to naturally overflow
# the real 20-message short-term memory.
#
# ------------------------------------------------------------
# WHY TWO PHASES (this is the fix)
# ------------------------------------------------------------
# Long-term (semantic) memory is only populated by
# run_periodic_consolidation(), which is intentionally a
# SEPARATE, periodic operation -- it is never called by the
# live loop, route_and_log(), ShortTermMemory, or
# add_normalized_message_with_routing().
#
# That means if we ask the "what suspicious activity happened
# earlier" question inside the SAME live session that produced
# the transfers, long-term memory retrieval will correctly
# return "No relevant memories found", because consolidation
# has not run yet. That is not a bug in the agent -- it is a
# sequencing bug in the OLD version of this test, which asked
# the long-term-memory question before any consolidation had
# happened.
#
# The fix: split the live conversation into two sessions.
#
#   Phase 1: login + 10 wire transfers
#            -> overflows STM (max_messages=20)
#            -> triggers Promote-or-Drop routing
#            -> promoted messages land in EpisodicMemory
#
#   [ run_periodic_consolidation() HERE, between sessions ]
#            -> moves promoted episodes into semantic
#               (long-term) memory
#
#   Phase 2: a NEW session (fresh login, since sessions don't
#            persist auth) that asks the suspicious-activity
#            question
#            -> long-term memory retrieval now has real data
#               to find
#
# This keeps consolidation exactly where the architecture says
# it belongs (a separate periodic pass), while still giving the
# final query something to actually retrieve.
# ============================================================

PHASE1_REQUESTS = [
    "Login with employee ID 4.",

    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-001 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-002 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-003 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-004 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-005 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-006 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-007 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-008 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-009 in IR.",
    "Initiate a wire transfer of 1000 from account 2 to FR-TEST-010 in IR.",
]

PHASE2_REQUESTS = [
    "Login with employee ID 4.",

    "What suspicious wire transfer activity happened earlier? "
    "Tell me the previous transfers and any pattern you noticed.",
]

# Kept for reporting / evidence-counting purposes so the report
# still reads as "one conversation" even though it technically
# ran as two sessions.
TEST_REQUESTS = PHASE1_REQUESTS + PHASE2_REQUESTS


# ============================================================
# LOAD REAL CLIENT
# ============================================================

def load_client_module():
    if not CLIENT_PATH.exists():
        raise FileNotFoundError(
            f"Client not found:\n{CLIENT_PATH}"
        )

    spec = importlib.util.spec_from_file_location(
        "client_module",
        CLIENT_PATH,
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
# RUN REAL CLIENT (now parameterized by request list, so it
# can be called once per phase/session)
# ============================================================

async def run_client_session(module, requests):
    inputs = iter(requests + ["exit"])
    original_input = builtins.input

    def fake_input(prompt=""):
        prompt_lower = str(prompt).lower()

        # Handle MCP elicitation automatically.
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
        with contextlib.redirect_stdout(captured), \
             contextlib.redirect_stderr(captured):

            await module.main()

    finally:
        builtins.input = original_input

    elapsed = time.perf_counter() - start

    return captured.getvalue(), elapsed


async def run_client():
    """
    Runs the real client as TWO separate sessions, with a
    periodic consolidation pass in between, so that the final
    long-term-memory question is asked only after semantic
    memory has actually been populated.
    """

    module = load_client_module()

    # ---- Phase 1: build up short-term/episodic memory ----
    phase1_output, phase1_elapsed = await run_client_session(
        module, PHASE1_REQUESTS
    )

    # ---- Consolidation: episodic -> semantic (long-term) ----
    consolidation_actions = run_periodic_consolidation()

    # ---- Phase 2: fresh session, now long-term memory has data ----
    phase2_output, phase2_elapsed = await run_client_session(
        module, PHASE2_REQUESTS
    )

    combined_output = (
        phase1_output
        + "\n\n[TEST] --- periodic consolidation ran here ---\n\n"
        + phase2_output
    )

    total_elapsed = phase1_elapsed + phase2_elapsed

    return module, combined_output, total_elapsed, consolidation_actions


# ============================================================
# HELPERS
# ============================================================

def count(output, pattern):
    return len(
        re.findall(
            pattern,
            output,
            re.IGNORECASE,
        )
    )


def has(output, pattern):
    return bool(
        re.search(
            pattern,
            output,
            re.IGNORECASE,
        )
    )


# ============================================================
# PERIODIC CONSOLIDATION
# ============================================================
#
# This now intentionally happens BETWEEN the two live sessions
# (after Phase 1, before Phase 2) instead of after everything.
#
# It is still NOT called by:
#   - the live loop
#   - route_and_log()
#   - ShortTermMemory
#   - add_normalized_message_with_routing()
#
# This still proves consolidation is a separate periodic
# operation -- it just proves it at the point in time where it
# actually needs to have run for long-term retrieval to have
# anything to find.
#
# ============================================================

def run_periodic_consolidation():
    from memory.semantic_memory.consolidation import run_consolidation

    return run_consolidation()


# ============================================================
# EVALUATION
# ============================================================

def evaluate(module, output, consolidation_actions):
    evidence = {}

    request_count = len(TEST_REQUESTS)

    # ========================================================
    # 1. HYBRID RAG
    # ========================================================

    rag_runs = count(
        output,
        r"\[HYBRID RAG\]\s*Searching",
    )

    evidence["Hybrid RAG executed for every request"] = (
        rag_runs >= request_count
    )

    # ========================================================
    # 2. HYBRID RAG RETURNED A STATUS
    # ========================================================

    rag_status_count = count(
        output,
        r"\[HYBRID RAG\]\s*[\r\n]+\s*Status:",
    )

    evidence["Hybrid RAG produced a status for every request"] = (
        rag_status_count >= request_count
    )

    # ========================================================
    # 3. SHORT-TERM MEMORY / SCRATCHPAD
    # ========================================================

    scratchpad_count = count(
        output,
        r"\[scratchpad\]",
    )

    evidence["Short-term memory and scratchpad remain active"] = (
        scratchpad_count >= request_count
    )

    evidence["Scratchpad reaches waiting state after requests"] = has(
        output,
        r"Waiting for next request",
    )

    # ========================================================
    # 4. SCRATCHPAD TOOL ACTIVITY
    # ========================================================

    evidence["Scratchpad records MCP tool activity"] = has(
        output,
        r"Tool call:",
    )

    # ========================================================
    # 5. PROMOTE-OR-DROP ROUTING
    # ========================================================

    forget_count = count(
        output,
        r"\[MEMORY\]\s*FORGET",
    )

    promote_count = count(
        output,
        r"\[MEMORY\]\s*PROMOTE",
    )

    routing_count = forget_count + promote_count

    evidence["Promote-or-drop routing fired"] = (
        routing_count >= 1
    )

    evidence["Promote-or-drop routing reasoning is visible"] = has(
        output,
        r"\[MEMORY\]\s*Reason:",
    )

    evidence["At least one message was forgotten"] = (
        forget_count >= 1
    )

    evidence["At least one message was promoted"] = (
        promote_count >= 1
    )

    # ========================================================
    # 6. EPISODIC MEMORY
    # ========================================================

    from memory.episodic_memory.episodic_memory import EpisodicMemory

    episodes_in_db = EpisodicMemory().get_recent_episodes(
        limit=50
    )

    evidence["Live conversation produced stored episodic memory"] = (
        len(episodes_in_db) >= 1
    )

    # ========================================================
    # 7. LONG-TERM MEMORY RETRIEVAL
    # ========================================================

    evidence["Long-term memory retrieval path executed"] = has(
        output,
        r"\[LONG-TERM MEMORY\]\s*("
        r"Relevant memories found|"
        r"No relevant memories found"
        r")",
    )

    retrieval_count = count(
        output,
        r"\[LONG-TERM MEMORY\]\s*Relevant memories found",
    )

    evidence["Long-term memory retrieved relevant memory at least once"] = (
        retrieval_count >= 1
    )

    # ========================================================
    # 8. LONG-TERM MEMORY POST-RETRIEVAL VERIFICATION
    # ========================================================

    evidence["Long-term memory relevance verification executed"] = has(
        output,
        r"\[LONG-TERM MEMORY\]\s*Supported:",
    )

    evidence["Long-term memory verification produced PASS or FAIL"] = (
        has(
            output,
            r"\[LONG-TERM MEMORY\]\s*Verification (PASSED|FAILED)",
        )
    )

    evidence["No JSON parsing failure occurred during memory verification"] = (
        not has(
            output,
            r"JSONDecodeError",
        )
    )

    # ========================================================
    # 9. LONG-TERM MEMORY POST-GENERATION VERIFICATION
    # ========================================================

    evidence["Long-term memory answer verification executed"] = has(
        output,
        r"\[LONG-TERM MEMORY\]\s*Verifying generated answer",
    )

    evidence["Long-term memory answer verification produced a boolean"] = (
        has(
            output,
            r"\[LONG-TERM MEMORY\]\s*Answer supported:\s*(True|False)",
        )
    )

    # ========================================================
    # 10. FINAL MEMORY-DEPENDENT QUERY
    # ========================================================

    evidence["Final memory-dependent query executed"] = has(
        output,
        r"What suspicious wire transfer activity happened earlier",
    )

    # ========================================================
    # 11. RAG + LONG-TERM MEMORY IN LIVE PIPELINE
    # ========================================================

    evidence["RAG and long-term memory are integrated"] = (
        evidence["Hybrid RAG executed for every request"]
        and evidence["Long-term memory retrieval path executed"]
    )

    # ========================================================
    # 12. MCP BANKING TOOLS
    # ========================================================

    evidence["MCP banking tool activity occurred"] = has(
        output,
        r"Tool call:",
    )

    # ========================================================
    # 13. HUMAN ELICITATION
    # ========================================================

    evidence["Human elicitation was exercised"] = has(
        output,
        r"\[TEST ELICITATION\]\s*no",
    )

    # ========================================================
    # 14. PERIODIC CONSOLIDATION
    # ========================================================
    #
    # Now evaluated as: did it run, between the two sessions,
    # and did it actually have something to consolidate.
    #
    # ========================================================

    evidence["Periodic consolidation pass ran independently"] = (
        consolidation_actions is not None
    )

    evidence["Consolidation processed at least one customer"] = (
        bool(consolidation_actions)
    )

    return evidence


# ============================================================
# BUILD REPORT
# ============================================================

def build_report(
    output,
    elapsed,
    evidence,
    consolidation_actions,
):
    passed = sum(
        1
        for value in evidence.values()
        if value
    )

    total = len(evidence)

    rag_runs = count(
        output,
        r"\[HYBRID RAG\]\s*Searching",
    )

    forget_count = count(
        output,
        r"\[MEMORY\]\s*FORGET",
    )

    promote_count = count(
        output,
        r"\[MEMORY\]\s*PROMOTE",
    )

    retrieval_count = count(
        output,
        r"\[LONG-TERM MEMORY\]\s*Relevant memories found",
    )

    lines = [
        "## Agent Memory & RAG End-to-End Integration Test",
        "",
        f"- **Run time:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Execution time:** {elapsed:.2f}s",
        f"- **Integration evidence:** **{passed}/{total} checks passed**",
        f"- **Requests executed:** {len(TEST_REQUESTS)} "
        f"(split across 2 sessions, consolidation run between them)",
        "- **Short-term memory capacity:** 20 messages "
        "(matches current client.py)",
        f"- **Hybrid RAG executions:** "
        f"{rag_runs}/{len(TEST_REQUESTS)}",
        f"- **Promote-or-drop decisions:** "
        f"{forget_count} forget, {promote_count} promote",
        f"- **Long-term memory retrievals:** "
        f"{retrieval_count}",
        f"- **Consolidation actions "
        f"(separate periodic pass, run between sessions):** "
        f"{len(consolidation_actions or [])}",
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
        "Session 1: User Request",
        "    |",
        "Short-Term Memory (max_messages=20)",
        "    |",
        "Scratchpad -> Context Strategy -> Hybrid RAG",
        "    |",
        "Long-Term Memory Retrieval (empty at this point)",
        "    |",
        "Agent -> MCP Banking Tool -> Human Elicitation",
        "    |",
        "New Agent Messages",
        "    |",
        "Short-Term Memory + Promote-or-Drop Router",
        "    |",
        "FORGET / PROMOTE  ->  Episodic Memory",
        "",
        "-- separate step, between sessions --",
        "",
        "Periodic Consolidation",
        "    |",
        "Semantic (Long-Term) Memory  <-- now populated",
        "",
        "-- Session 2 (fresh login) --",
        "",
        "User Request (\"what suspicious activity happened earlier\")",
        "    |",
        "Hybrid RAG + Long-Term Memory Retrieval (now finds data)",
        "    |",
        "Long-Term Memory Verification -> Agent -> Answer",
        "    |",
        "Long-Term Memory Answer Verification",
        "```",
        "",
        "### Test Requests",
        "",
        "**Phase 1 (session 1):**",
        "",
    ]

    for index, request in enumerate(PHASE1_REQUESTS, start=1):
        lines.append(f"{index}. `{request}`")

    lines += [
        "",
        "**Phase 2 (session 2, after consolidation):**",
        "",
    ]

    for index, request in enumerate(PHASE2_REQUESTS, start=1):
        lines.append(f"{index}. `{request}`")

    lines += [
        "",
        "### What This Test Proves",
        "",
        "- The real client executes Hybrid RAG before every request.",
        "- The real ShortTermMemory configuration "
        "(max_messages=20) is exercised.",
        "- Scratchpad state survives across each live session.",
        "- MCP tool activity is recorded in the scratchpad.",
        "- Short-term memory overflow reaches the real "
        "Promote-or-Drop Router.",
        "- Router decisions are visible through "
        "FORGET/PROMOTE markers and reasoning.",
        "- Promoted episodes are independently verified "
        "through EpisodicMemory.",
        "- Periodic semantic consolidation is executed as a "
        "separate operation, run between the two live sessions "
        "(not called by the live loop itself).",
        "- Because consolidation runs BEFORE the final query, "
        "long-term memory retrieval has real data to find, so "
        "the retrieval, relevance-verification, and "
        "answer-verification checks reflect actual behavior "
        "instead of failing due to test sequencing.",
        "- Human elicitation is exercised by automatically "
        "answering `no` in the test.",
        "",
        "### Run",
        "",
        "```bash",
        "python -u client/test_client.py",
        "```",
        "",
        "### Raw Output",
        "",
        "```text",
        output[-10000:],
        "```",
        "",
        "### Consolidation Actions",
        "",
        "```text",
        "\n".join(
            str(action)
            for action in (
                consolidation_actions or []
            )
        )
        or "(no unconsolidated episodes were available at run time)",
        "```",
        "",
    ]

    if passed == total:
        lines.append(
            "**Result: PASSED — Memory, RAG, and context "
            "management are demonstrated end-to-end.**"
        )
    else:
        lines.append(
            f"**Result: PARTIAL — "
            f"{total - passed} checks failed.**"
        )

    lines.append("")

    return "\n".join(lines)


# ============================================================
# UPDATE README
# ============================================================

def update_readme(report):
    if README.exists():
        readme = README.read_text(
            encoding="utf-8"
        )
    else:
        readme = "# Sterling & Vance Bank\n"

    marker = (
        "## Agent Memory & RAG End-to-End Integration Test"
    )

    if marker in readme:
        readme = (
            readme.split(marker)[0].rstrip()
            + "\n\n"
        )
    else:
        readme = (
            readme.rstrip()
            + "\n\n"
        )

    README.write_text(
        readme + report,
        encoding="utf-8",
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 65)
    print(
        "STERLING & VANCE - MEMORY & RAG END-TO-END TEST"
    )
    print("=" * 65)

    print(
        f"Project root: {PROJECT_ROOT}"
    )

    print(
        f"Client file: {CLIENT_PATH}"
    )

    print(
        f"README: {README}"
    )

    print()

    try:
        module, output, elapsed, consolidation_actions = asyncio.run(
            run_client()
        )

    except Exception as exc:
        report = "\n".join(
            [
                "## Agent Memory & RAG End-to-End Integration Test",
                "",
                "- **Result:** FAILED",
                f"- **Error:** "
                f"`{type(exc).__name__}: {exc}`",
                "",
                "```text",
                str(exc),
                "```",
                "",
            ]
        )

        update_readme(report)

        print(report)

        raise

    # ========================================================
    # EVALUATE
    # ========================================================

    evidence = evaluate(
        module,
        output,
        consolidation_actions,
    )

    report = build_report(
        output,
        elapsed,
        evidence,
        consolidation_actions,
    )

    update_readme(report)

    print(report)

    print(
        "\nREADME.md updated successfully."
    )

    if not all(evidence.values()):
        sys.exit(1)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()