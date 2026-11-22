"""Local model. It proposes search language and screens titles; it never supplies facts."""
import json

from .net import SourceError


def ask(client, op, system, user, schema, tokens=600):
    cfg = client.cfg["llm"]
    body = {
        "model": cfg["model"], "stream": False, "think": False, "format": schema,
        "options": {"temperature": 0, "seed": 7, "num_predict": tokens},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    try:
        reply, _ = client.request("ollama", op, cfg["url"], body=body, timeout=cfg["timeout"])
        out = json.loads(reply["message"]["content"])
        return out if isinstance(out, dict) else None
    except (SourceError, KeyError, ValueError):
        return None
