"""
Consolidation layer for semantic memory (issue #41).

A genuinely separate, PERIODIC pass over episodic_memory - never
triggered at write time, never called by the promote-or-drop router.
Run it manually or on a schedule via run_consolidation.py.

For each customer with unconsolidated episodes (EpisodicMemory.
get_unconsolidated_episodes()), derives an implied `risk_level` fact
per episode and reconciles it against the current active semantic
fact for that customer:
  - no active fact yet          -> insert first version
  - derived value == current    -> repeat-pattern reinforcement
                                    (escalate one severity level)
  - derived value != current    -> REAL CONFLICT: newer episode wins,
                                    old fact superseded (versioned,
                                    never silently overwritten),
                                    contradiction_note cites both
                                    episode_ids and states why the
                                    newer one won (recency of
                                    investigation).

Fact-derivation rule (flags -> implied risk_level), confirmed design:
  sanctions or self_dealing present          -> high, regardless of decision
  structuring only, decision approved/cleared -> medium
  structuring only, any other/unknown decision -> high (conservative default)
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "episodic_memory"))
from semantic_memory import SemanticMemory  # noqa: E402
from episodic_memory import EpisodicMemory  # noqa: E402

_SEVERITY = {"low": 0, "medium": 1, "high": 2}
_SEVERITY_NAMES = {v: k for k, v in _SEVERITY.items()}

_CLEARED_DECISIONS = {"approved", "cleared"}
_BLOCKING_DECISIONS = {"rejected", "denied", "escalated"}


def _normalize_decision(decision: Optional[str]) -> str:
    if decision is None:
        return "unknown"
    d = decision.strip().lower()
    if d in _CLEARED_DECISIONS:
        return "cleared"
    if d in _BLOCKING_DECISIONS:
        return "blocking"
    return "unknown"


def derive_risk_level(flags: Optional[str], decision: Optional[str]) -> Optional[str]:
    """Turn one episode's flags/decision into an implied risk_level, or
    None if this episode carries no risk-relevant flags at all."""
    if not flags:
        return None
    flags_list = [f.strip() for f in flags.split(",") if f.strip()]

    if "sanctions" in flags_list or "self_dealing" in flags_list:
        return "high"

    if "structuring" in flags_list:
        norm = _normalize_decision(decision)
        return "medium" if norm == "cleared" else "high"

    return None


def _escalate(level: str) -> str:
    """Bump one severity level, capped at 'high' - the repeat-offender rule."""
    rank = min(_SEVERITY[level] + 1, 2)
    return _SEVERITY_NAMES[rank]


def run_consolidation() -> List[Dict]:
    """
    The periodic pass. Returns a list of action records (for the demo
    and for tests) describing what happened per customer - inserted
    first fact, reinforced/escalated, or resolved a real conflict.
    """
    episodic = EpisodicMemory()
    semantic = SemanticMemory()

    episodes = episodic.get_unconsolidated_episodes()  # ASC by promoted_at
    by_customer: Dict[int, List] = {}
    for ep in episodes:
        if ep["customer_id"] is None:
            continue
        by_customer.setdefault(ep["customer_id"], []).append(ep)

    actions = []

    for customer_id, customer_episodes in by_customer.items():
        current_fact = semantic.get_active_fact("customer", customer_id, "risk_level")
        current_value = current_fact["fact_value"] if current_fact else None
        consolidated_ids = []

        for ep in customer_episodes:
            derived = derive_risk_level(ep["flags"], ep["decision"])
            consolidated_ids.append(ep["episode_id"])

            if derived is None:
                actions.append({
                    "customer_id": customer_id, "episode_id": ep["episode_id"],
                    "action": "skipped", "reason": "no risk-relevant flags on this episode",
                })
                continue

            if current_fact is None:
                fact_id = semantic.insert_fact_version(
                    entity_type="customer", entity_id=customer_id,
                    fact_key="risk_level", fact_value=derived,
                    source_episode_ids=[ep["episode_id"]],
                )
                actions.append({
                    "customer_id": customer_id, "episode_id": ep["episode_id"],
                    "action": "inserted_first_version", "fact_id": fact_id,
                    "value": derived,
                })
                current_fact = semantic.get_active_fact("customer", customer_id, "risk_level")
                current_value = derived
                continue

            if derived == current_value:
                escalated = _escalate(current_value)
                if escalated == current_value:
                    actions.append({
                        "customer_id": customer_id, "episode_id": ep["episode_id"],
                        "action": "reinforced_no_change",
                        "reason": f"already at max severity ({current_value})",
                    })
                    continue
                note = (
                    f"Repeat pattern: episode #{ep['episode_id']} independently "
                    f"implies '{derived}' again for this customer, same as the "
                    f"current active fact (fact_id={current_fact['fact_id']}) - "
                    f"escalated to '{escalated}' as a repeat-offender signal."
                )
                new_fact_id = semantic.insert_fact_version(
                    entity_type="customer", entity_id=customer_id,
                    fact_key="risk_level", fact_value=escalated,
                    source_episode_ids=(
                        [int(i) for i in current_fact["source_episode_ids"].split(",")]
                        + [ep["episode_id"]]
                    ),
                    contradiction_note=note,
                )
                semantic.supersede_fact(current_fact["fact_id"], new_fact_id)
                actions.append({
                    "customer_id": customer_id, "episode_id": ep["episode_id"],
                    "action": "repeat_escalated", "fact_id": new_fact_id,
                    "old_value": current_value, "new_value": escalated,
                })
                current_fact = semantic.get_active_fact("customer", customer_id, "risk_level")
                current_value = escalated
                continue

            # --- Real conflict: derived != current_value ---
            note = (
                f"Contradiction resolved: episode #{current_fact['source_episode_ids']} "
                f"(prior fact_id={current_fact['fact_id']}) implied '{current_value}', "
                f"but newer episode #{ep['episode_id']} implies '{derived}'. "
                f"Newer episode wins (resolved on recency of investigation, not "
                f"insertion order) - old fact superseded, not overwritten."
            )
            new_fact_id = semantic.insert_fact_version(
                entity_type="customer", entity_id=customer_id,
                fact_key="risk_level", fact_value=derived,
                source_episode_ids=[ep["episode_id"]],
                contradiction_note=note,
            )
            semantic.supersede_fact(current_fact["fact_id"], new_fact_id)
            actions.append({
                "customer_id": customer_id, "episode_id": ep["episode_id"],
                "action": "conflict_resolved", "fact_id": new_fact_id,
                "old_value": current_value, "new_value": derived,
                "note": note,
            })
            current_fact = semantic.get_active_fact("customer", customer_id, "risk_level")
            current_value = derived

        episodic.mark_consolidated(consolidated_ids)

    return actions