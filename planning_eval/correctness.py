from __future__ import annotations
import re
from typing import Any

SUCCESS_THRESHOLD = 0.70

def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).lower()
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = text.replace(",", "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s.$%/:#=]", " ", text)
    return text.strip()

def result_to_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, (int, float, bool)):
        return str(result)
    if isinstance(result, dict):
        return " ".join(f"{key} {result_to_text(value)}" for key, value in result.items())
    if isinstance(result, (list, tuple, set)):
        return " ".join(result_to_text(item) for item in result)
    if hasattr(result, "model_dump"):
        try:
            return result_to_text(result.model_dump())
        except Exception:
            pass
    attributes = (
        "output",
        "answer",
        "content",
        "state",
        "result",
        "final_answer",
        "trials",
        "memory",
        "reflection",
        "reflections",
        "feedback",
        "steps",
        "best_candidate",
        "best_score",
        "environment_score",
        "model_score",
        "uct_visit_counts",
    )
    parts: list[str] = []
    for attribute in attributes:
        value = getattr(result, attribute, None)
        if value is not None:
            parts.append(f"{attribute}: {result_to_text(value)}")
    return " ".join(parts) if parts else str(result)

def phrase_pattern(phrase: str) -> str:
    normalized = normalize_text(phrase)
    escaped = re.escape(normalized)
    return escaped.replace(r"\ ", r"\s+")

def contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    text = normalize_text(text)
    pattern = phrase_pattern(phrase)
    return re.search(rf"(?<!\w){pattern}(?!\w)", text) is not None

def contains_any(text: str, phrases: list[str]) -> bool:
    return any(contains_phrase(text, phrase) for phrase in phrases if phrase)

ALIASES: dict[str, list[str]] = {
    "IR": ["IR", "Iran", "Iranian"],
    "US": ["US", "USA", "United States", "United States of America"],
    "FR": ["FR", "France", "French"],
    "GB": ["GB", "UK", "United Kingdom", "Great Britain", "Britain"],
    "structuring": ["structuring", "structured deposits", "structuring activity", "structuring pattern"],
    "sanctions exposure": ["sanctions exposure", "sanction exposure", "sanctions risk", "sanction risk", "sanctioned destination", "sanctioned country"],
    "self dealing": ["self dealing", "self-dealing", "conflict of interest", "employee conflict", "employee conflict of interest"],
    "flagged": ["flagged", "held", "on hold"],
    "denied": ["denied", "rejected", "rejection"],
}

def aliases_for(value: Any) -> list[str]:
    normalized = normalize_text(value)
    for key, aliases in ALIASES.items():
        if normalize_text(key) == normalized:
            return aliases
    return [str(value)]

def entity_aliases(entity: str, value: Any) -> list[str]:
    entity = normalize_text(entity)
    value = normalize_text(value)
    aliases = [
        f"{entity} {value}",
        f"{entity} id {value}",
        f"{entity} #{value}",
    ]
    if "transaction" in entity:
        aliases.extend([
            f"transaction {value}",
            f"transaction id {value}",
            f"transaction #{value}",
            f"txn {value}",
        ])
    elif "wire" in entity or "transfer" in entity:
        aliases.extend([
            f"wire {value}",
            f"wire transfer {value}",
            f"wire transfer id {value}",
            f"transfer {value}",
            f"transfer id {value}",
        ])
    elif "account" in entity:
        aliases.extend([
            f"account {value}",
            f"account id {value}",
            f"account #{value}",
        ])
    elif "customer" in entity:
        aliases.extend([
            f"customer {value}",
            f"customer id {value}",
            f"customer #{value}",
        ])
    elif "employee" in entity:
        aliases.extend([
            f"employee {value}",
            f"employee id {value}",
        ])
    elif "review" in entity:
        aliases.extend([
            f"review {value}",
            f"compliance review {value}",
        ])
    return aliases

def find_entity_context(text: str, entity: str, value: Any, window: int = 120) -> list[str]:
    normalized_text = normalize_text(text)
    contexts: list[str] = []
    for alias in entity_aliases(entity, value):
        pattern = phrase_pattern(alias)
        for match in re.finditer(pattern, normalized_text):
            start = max(0, match.start() - window)
            end = min(len(normalized_text), match.end() + window)
            contexts.append(normalized_text[start:end])
    return contexts

def context_contains(contexts: list[str], phrases: list[str]) -> bool:
    return any(contains_any(context, phrases) for context in contexts)

def match_entity_fact(entity: str, entity_id: Any, expected_value: Any, text: str) -> bool:
    contexts = find_entity_context(text, entity, entity_id)
    if not contexts:
        return False
    if isinstance(expected_value, bool):
        return any(match_boolean(entity, expected_value, context) for context in contexts)
    if isinstance(expected_value, (int, float)):
        return any(contains_number(context, expected_value) for context in contexts)
    return context_contains(contexts, aliases_for(expected_value))

def contains_number(text: str, value: int | float) -> bool:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    value_text = str(value)
    escaped = re.escape(value_text)
    patterns = [
        rf"(?<![\d.]){escaped}(?![\d.])",
        rf"\${escaped}(?![\d.])",
    ]
    return any(re.search(pattern, normalize_text(text)) for pattern in patterns)

def match_boolean(key: str, value: bool, text: str) -> bool:
    key = normalize_text(key)
    aliases = aliases_for(key)
    negative = [
        f"no {key}",
        f"no evidence of {key}",
        f"not {key}",
        f"{key} false",
        f"{key} absent",
        f"without {key}",
    ]
    if value:
        if contains_any(text, negative):
            return False
        return contains_any(text, aliases)
    return contains_any(text, negative)

def match_scalar(key: str, value: Any, text: str) -> bool:
    normalized_key = normalize_text(key)
    if isinstance(value, bool):
        return match_boolean(key, value, text)
    if isinstance(value, int):
        entity_map = {
            "customer id": "customer",
            "account id": "account",
            "employee id": "employee",
            "review id": "review",
        }
        if normalized_key in entity_map:
            return bool(find_entity_context(text, entity_map[normalized_key], value))
        if "transaction id" in normalized_key:
            return bool(find_entity_context(text, "transaction", value))
        if "wire transfer id" in normalized_key:
            return bool(find_entity_context(text, "wire transfer", value))
        return contains_number(text, value)
    if isinstance(value, float):
        return contains_number(text, value)
    if isinstance(value, str):
        return contains_any(text, aliases_for(value))
    return contains_phrase(text, str(value))

def parse_entity_key(key: str) -> tuple[str, int, str] | None:
    normalized = normalize_text(key)
    patterns = [
        (r"wire transfer (\d+) (.+)", "wire transfer"),
        (r"transaction (\d+) (.+)", "transaction"),
        (r"account (\d+) (.+)", "account"),
        (r"customer (\d+) (.+)", "customer"),
        (r"employee (\d+) (.+)", "employee"),
        (r"review (\d+) (.+)", "review"),
    ]
    for pattern, entity in patterns:
        match = re.fullmatch(pattern, normalized)
        if match:
            return entity, int(match.group(1)), match.group(2)
    return None

def evaluate_entity_key(key: str, value: Any, text: str) -> tuple[int, int, list[str]]:
    parsed = parse_entity_key(key)
    if parsed is None:
        return 0, 0, []
    entity, entity_id, attribute = parsed
    if isinstance(value, dict):
        matched = 0
        expected = 0
        missing: list[str] = []
        for child_key, child_value in value.items():
            m, e, miss = evaluate_entity_fact(entity, entity_id, child_key, child_value, text)
            matched += m
            expected += e
            missing.extend(miss)
        return matched, expected, missing
    return evaluate_entity_fact(entity, entity_id, attribute, value, text)

def evaluate_entity_fact(entity: str, entity_id: int, attribute: str, value: Any, text: str) -> tuple[int, int, list[str]]:
    contexts = find_entity_context(text, entity, entity_id)
    if not contexts:
        return 0, 1, [f"{entity} {entity_id} not found"]
    if isinstance(value, bool):
        ok = any(match_boolean(attribute, value, context) for context in contexts)
    elif isinstance(value, (int, float)):
        ok = any(contains_number(context, value) for context in contexts)
    elif isinstance(value, str):
        ok = context_contains(contexts, aliases_for(value))
    else:
        ok = context_contains(contexts, [str(value)])
    if ok:
        return 1, 1, []
    return 0, 1, [f"{entity} {entity_id} {attribute}={value}"]

def evaluate_list(key: str, values: list[Any], text: str) -> tuple[int, int, list[str]]:
    if not values:
        return 1, 1, []
    matched = 0
    expected = 0
    missing: list[str] = []
    for value in values:
        if isinstance(value, dict):
            m, e, miss = evaluate_dict(value, text, parent_key=key)
            matched += m
            expected += e
            missing.extend(miss)
            continue
        expected += 1
        if match_scalar(key, value, text):
            matched += 1
        else:
            missing.append(f"{key} contains {value}")
    return matched, expected, missing

def evaluate_dict(value: dict[str, Any], text: str, parent_key: str = "") -> tuple[int, int, list[str]]:
    matched = 0
    expected = 0
    missing: list[str] = []
    for key, child_value in value.items():
        full_key = f"{parent_key}.{key}" if parent_key else key
        m, e, miss = evaluate_expected_fact(full_key, child_value, text)
        matched += m
        expected += e
        missing.extend(miss)
    return matched, expected, missing

def evaluate_expected_fact(key: str, value: Any, text: str) -> tuple[int, int, list[str]]:
    entity_result = evaluate_entity_key(key, value, text)
    if entity_result[1] > 0:
        return entity_result
    if isinstance(value, dict):
        return evaluate_dict(value, text, parent_key=key)
    if isinstance(value, list):
        return evaluate_list(key, value, text)
    if match_scalar(key, value, text):
        return 1, 1, []
    return 0, 1, [f"{key}={value}"]

def evaluate_structured_records(records: list[Any], text: str, record_type: str) -> tuple[int, int, list[str]]:
    matched = 0
    expected = 0
    missing: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            expected += 1
            if contains_phrase(text, str(record)):
                matched += 1
            else:
                missing.append(f"{record_type}: {record}")
            continue
        entity_id = (
            record.get("id")
            or record.get("transaction_id")
            or record.get("wire_transfer_id")
            or record.get("review_id")
        )
        if entity_id is None:
            m, e, miss = evaluate_dict(record, text)
            matched += m
            expected += e
            missing.extend(miss)
            continue
        for attribute, value in record.items():
            if attribute in {"id", "transaction_id", "wire_transfer_id", "review_id"}:
                continue
            m, e, miss = evaluate_entity_fact(record_type, int(entity_id), attribute, value, text)
            matched += m
            expected += e
            missing.extend(miss)
    return matched, expected, missing

def evaluate_required_risk_factors(factors: list[Any], text: str) -> tuple[int, int, list[str]]:
    matched = 0
    expected = len(factors)
    missing: list[str] = []
    for factor in factors:
        factor = str(factor)
        normalized = normalize_text(factor)
        if normalized == "employee relationship":
            ok = contains_any(text, [
                "employee relationship",
                "employee related",
                "employee is related",
                "related employee",
                "relationship between employee and customer",
            ])
        elif normalized == "compliance reviews":
            ok = contains_any(text, ["compliance review", "compliance reviews"])
        else:
            ok = contains_any(text, aliases_for(factor))
        if ok:
            matched += 1
        else:
            missing.append(f"required risk factor: {factor}")
    return matched, expected, missing

def evaluate_invalid_dependencies(dependencies: list[Any], text: str) -> tuple[int, int, list[str]]:
    if not dependencies:
        return 0, 0, []
    normalized_text = normalize_text(text)
    expected = len(dependencies)
    matched = 0
    missing: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            expected_text = str(dependency)
            if contains_phrase(normalized_text, expected_text):
                matched += 1
            else:
                missing.append(f"invalid dependency: {dependency}")
            continue
        task = str(dependency.get("task", ""))
        depends_on = dependency.get("depends_on", [])
        task_present = contains_phrase(normalized_text, task)
        dependency_present = any(contains_phrase(normalized_text, str(item)) for item in depends_on)
        if task_present and dependency_present:
            matched += 1
        else:
            missing.append(f"invalid dependency: {dependency}")
    return matched, expected, missing

def evaluate_expected_behavior(behavior: str, text: str) -> tuple[int, int, list[str]]:
    normalized = normalize_text(behavior)
    if "validation must fail" in normalized and "before" in normalized and "executed" in normalized:
        validation_failed = contains_any(text, [
            "validation failed",
            "validation error",
            "invalid plan",
            "cycle detected",
            "cyclic dependency",
            "dependency cycle",
            "plan rejected",
        ])
        zero_execution = contains_any(text, [
            "0 tasks",
            "zero tasks",
            "no tasks executed",
            "no investigation task executed",
            "tasks started: 0",
            "tasks completed: 0",
        ])
        if validation_failed and zero_execution:
            return 1, 1, []
        missing = []
        if not validation_failed:
            missing.append("validation did not clearly fail")
        if not zero_execution:
            missing.append("execution was not shown to be zero")
        return 0, 1, missing
    if contains_phrase(text, behavior):
        return 1, 1, []
    return 0, 1, [f"expected behavior: {behavior}"]

def evaluate_expected_completed_tasks(expected_value: int, result: Any, text: str) -> tuple[int, int, list[str]]:
    if isinstance(result, dict):
        for key in ("completed_tasks", "tasks_completed", "number_of_completed_tasks"):
            if key in result:
                try:
                    if int(result[key]) == expected_value:
                        return 1, 1, []
                    return 0, 1, [f"expected completed tasks: {expected_value}"]
                except (TypeError, ValueError):
                    pass
    patterns = [
        r"completed tasks\s*[:=]\s*(\d+)",
        r"tasks completed\s*[:=]\s*(\d+)",
        r"completed\s*[:=]\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalize_text(text))
        if match:
            actual = int(match.group(1))
            if actual == expected_value:
                return 1, 1, []
            return 0, 1, [f"expected completed tasks: {expected_value}; got {actual}"]
    return 0, 1, [f"completed task count not found; expected {expected_value}"]

def evaluate_case_correctness(*, case: dict[str, Any], result: Any) -> dict[str, Any]:
    text = result_to_text(result)
    if not text.strip():
        return {
            "success": False,
            "score": 0.0,
            "matched": 0,
            "expected": 0,
            "missing": ["Empty agent result."],
            "result_text": "",
        }
    expected_facts = case.get("expected_facts", {})
    matched = 0
    expected = 0
    missing: list[str] = []
    for key, value in expected_facts.items():
        normalized_key = normalize_text(key)
        if normalized_key == "required risk factors":
            m, e, miss = evaluate_required_risk_factors(value, text)
        elif normalized_key == "invalid dependencies":
            m, e, miss = evaluate_invalid_dependencies(value, text)
        elif normalized_key == "expected behavior":
            m, e, miss = evaluate_expected_behavior(str(value), text)
        elif normalized_key == "expected completed tasks":
            m, e, miss = evaluate_expected_completed_tasks(int(value), result, text)
        elif normalized_key in {"cash deposits", "wire transfers", "transactions", "compliance reviews"} and isinstance(value, list):
            record_type = normalized_key.rstrip("s")
            if record_type == "cash depo":
                record_type = "cash deposit"
            m, e, miss = evaluate_structured_records(value, text, record_type)
        else:
            m, e, miss = evaluate_expected_fact(key, value, text)
        matched += m
        expected += e
        missing.extend(miss)
    missing = list(dict.fromkeys(missing))
    score = matched / expected if expected else 0.0
    success = expected > 0 and score >= SUCCESS_THRESHOLD
    return {
        "success": success,
        "score": round(score, 4),
        "matched": matched,
        "expected": expected,
        "missing": missing,
        "result_text": text,
    }
