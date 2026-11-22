"""Institution and author identity. When in doubt, records stay separate."""
import re

from .text import clean, fold

IIT_CITIES = {
    "kharagpur": "Kharagpur", "bombay": "Bombay", "mumbai": "Bombay", "madras": "Madras", "chennai": "Madras",
    "kanpur": "Kanpur", "delhi": "Delhi", "guwahati": "Guwahati", "roorkee": "Roorkee", "ropar": "Ropar",
    "bhubaneswar": "Bhubaneswar", "gandhinagar": "Gandhinagar", "hyderabad": "Hyderabad", "jodhpur": "Jodhpur",
    "patna": "Patna", "indore": "Indore", "mandi": "Mandi", "varanasi": "BHU", "bhu": "BHU",
    "palakkad": "Palakkad", "tirupati": "Tirupati", "dhanbad": "Dhanbad", "bhilai": "Bhilai", "goa": "Goa",
    "jammu": "Jammu", "dharwad": "Dharwad",
}
NIT_CITIES = ("tiruchirappalli", "trichy", "surathkal", "warangal", "rourkela", "calicut", "durgapur", "silchar",
              "jamshedpur", "kurukshetra", "patna", "raipur", "agartala", "srinagar", "hamirpur", "jalandhar",
              "allahabad", "bhopal", "jaipur", "nagpur", "surat", "meghalaya", "goa", "puducherry", "delhi",
              "manipur", "mizoram", "nagaland", "sikkim", "uttarakhand")
IISER_CITIES = ("pune", "kolkata", "mohali", "bhopal", "thiruvananthapuram", "tirupati", "berhampur")
ACADEMIC = re.compile(
    r"universit|institut|college|school|academy|laborator|research (?:centre|center)|\bcsir\b"
    r"|\b(?:iit|nit|iisc|iiser|iiit|bits|jncasr)\b|vidyapeeth|vishwavidyalaya", re.I)
COMPANY = re.compile(
    r"\b(?:ltd|limited|pvt|inc|corporation|corp|llp|gmbh|plc|industries|motors|pharmaceuticals)\b", re.I)


def in_country(affiliation, country="India"):
    if re.search(rf"\b{re.escape(country)}\b", affiliation, re.I):
        return True
    if country != "India":
        return False
    # Publishers often omit the country. These institution names exist only in India.
    place = institution(affiliation) or ""
    return place.startswith(("IIT ", "IISER ", "IISc ", "NISER ", "JNCASR")) or place in (
        "BITS Pilani", "BITS Pilani Goa", "BITS Pilani Hyderabad")


def is_company(affiliation):
    return bool(COMPANY.search(affiliation)) and not re.search(
        r"universit|college|institute of (?:technology|science)|council of", affiliation, re.I)


def first_present(folded, options):
    hits = [(folded.find(f" {o} "), o) for o in options if f" {o} " in folded]
    return min(hits)[1] if hits else None


def institution(affiliation):
    raw = clean(affiliation)
    raw = re.sub(r"\s*\((?:an? )?deemed[- ]to[- ]be[^)]*\)", "", raw, flags=re.I)
    if is_company(raw):
        return None
    f = f" {fold(raw)} "
    if "indian institute of technology" in f or " iit " in f:
        start = f.find("indian institute of technology")
        tail = f[start if start >= 0 else f.find(" iit "):]
        city = first_present(tail, IIT_CITIES) or first_present(f, IIT_CITIES)
        return f"IIT {IIT_CITIES[city]}" if city else None
    if "indian institute of science education" in f or " iiser " in f:
        city = first_present(f, IISER_CITIES)
        return f"IISER {city.title()}" if city else None
    if "indian institute of science " in f or " iisc " in f:
        return "IISc Bangalore"
    if "national institute of science education and research" in f or " niser " in f:
        return "NISER Bhubaneswar"
    if "birla institute of technology and science" in f or " bits pilani " in f:
        for key, campus in (("goa", "Goa"), ("hyderabad", "Hyderabad"), ("dubai", "Dubai")):
            if f" {key} " in f:
                return f"BITS Pilani {campus}"
        return "BITS Pilani"
    if "national institute of technology" in f or " nit " in f:
        city = first_present(f, NIT_CITIES)
        if city:
            return "NIT " + {"trichy": "Tiruchirappalli"}.get(city, city.title())
    if "jawaharlal nehru centre for advanced" in f or " jncasr " in f:
        return "JNCASR"
    parts = [p.strip() for p in re.split(r"[,;]", raw) if ACADEMIC.search(p)]
    for pattern in (r"universit|vidyapeeth|vishwavidyalaya", r"institut|college|\bcsir\b", r"."):
        for part in parts:
            department = re.match(r"(?:department|dept|school|faculty|division|centre|center) ", part, re.I)
            if re.search(pattern, part, re.I) and (not department or pattern == "."):
                return trim_university(part)[:110]
    return None


NOT_IN_NAME = set("""department dept school faculty institute college centre center division laboratory science sciences
chemistry physics engineering technology medicine biotechnology mathematics management studies research of and astrophysics""".split())


def trim_university(part):
    """'Department of Chemistry GLA University Mathura India' becomes 'GLA University'."""
    words = part.split()
    for i, word in enumerate(words):
        if not re.match(r"universit|vidyapeeth|vishwavidyalaya", word, re.I):
            continue
        if i + 2 < len(words) and words[i + 1].lower() == "of":
            end = i + 3
        else:
            end = i + 1
        start = i
        while start > 0 and i - start < 4 and fold(words[start - 1]) not in NOT_IN_NAME:
            start -= 1
        return " ".join(words[start:end])
    return part


def full_given(given):
    """True for 'Manu', false for 'M.' or 'M. S.'."""
    return any(len(word) > 1 for word in given.replace(".", " ").split())


def name_key(given, family):
    return fold(f"{given} {family}")


def initials_key(given, family):
    given = fold(given)
    return f"{given[:1]} {fold(family)}"
