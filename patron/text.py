import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime, timezone

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


def clean(value):
    """Plain text with markup and email addresses removed."""
    value = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", EMAIL.sub("", value)).strip()


def fold(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value.replace("&", " and ")).strip()


def stem_list(value):
    words = fold(value).split()
    return [(w[:-1] if len(w) > 3 and w.endswith("s") else w)[:6] for w in words]


def stems(value):
    """Crude word stems, so 'clays' matches 'clay' and 'emissions' matches 'emission'."""
    return set(stem_list(value))


def has_phrase(value, phrase):
    """The phrase's words, adjacent and in order."""
    return f" {' '.join(stem_list(phrase))} " in f" {' '.join(stem_list(value))} "


def mentions(haystack, name):
    """Whole-word match, so 'JK Cement' does not match 'JK Lakshmi Cement'."""
    needle = fold(name)
    return bool(needle) and f" {needle} " in f" {fold(haystack)} "
