import json
import re

from .config import settings


def enabled() -> bool:
    return bool(settings.anthropic_api_key)


def complete(system: str, user: str, max_tokens: int = 1000) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.anthropic_model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if b.type == "text")


def complete_json(system: str, user: str) -> dict:
    raw = complete(system, user)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    return json.loads(raw)
