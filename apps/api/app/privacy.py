import re


def redact(text: str) -> str:
    text = re.sub(
        r"(?i)\b(password|passwd|pwd|secret|api[_ -]?key|token)\s*(?:is\s+|[:=]\s*)\S+",
        r"\1 [REDACTED]",
        text,
    )
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", text)
    text = re.sub(r"(?<!\w)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\w)", "[PHONE]", text)
    text = re.sub(r"\b\d{7,}\b|\b(?=[A-Za-z0-9_-]{16,}\b)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+\b", "[ID]", text)
    return text


def redact_values(value):
    """Redact strings without corrupting JSON delimiters or schema keys."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_values(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_values(item) for key, item in value.items()}
    return value
