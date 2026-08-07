"""
Standalone entry point for the consolidation pass (issue #41).

Proves this is a genuinely separate, periodic process - not something
that fires automatically when the router promotes an episode. Run this
whenever you want unconsolidated episodes folded into semantic_memory.

Usage (from project root): python memory/semantic_memory/run_consolidation.py
"""

from consolidation import run_consolidation


def main():
    actions = run_consolidation()
    if not actions:
        print("No unconsolidated episodes to process.")
        return

    print(f"=== consolidation pass: {len(actions)} action(s) ===")
    for a in actions:
        print(a)


if __name__ == "__main__":
    main()