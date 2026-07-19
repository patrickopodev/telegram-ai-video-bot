import os
import re
from dispatcher.bot.validation import validate_prompt
from dispatcher.bot.rate_limit import check_rate_limit

MAX_PROMPT_LENGTH = 300

BLOCKED_TERMS = {"csam", "cp", "child", "rape", "sexual violence", "extreme violence"}


def validate_prompt(prompt: str, model: str = "ltx-video") -> tuple[bool, str]:
    if len(prompt) > MAX_PROMPT_LENGTH:
        return False, f"Prompt too long (max {MAX_PROMPT_LENGTH} chars)."

    lowered = prompt.lower()
    if any(term in lowered for term in BLOCKED_TERMS):
        return False, "Prompt violates content policy."

    if not re.search(r"[a-zA-Z]", prompt):
        return False, "Prompt must contain readable text."

    return True, ""