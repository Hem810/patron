import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def data_dir():
    path = Path(os.environ.get("PATRON_DATA") or ROOT / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def load():
    return json.loads((ROOT / "config.json").read_text())
