"""Read a research budget from the customer's words. Anything unclear becomes "unclear", never a guess."""
import re

WORDS = {word: n for n, word in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
WORDS.update(thirty=30, forty=40, fifty=50, sixty=60, seventy=70, eighty=80, ninety=90, hundred=100)
SPOKEN = "|".join(sorted(WORDS, key=len, reverse=True))

AMOUNT = re.compile(
    rf"(?:(?P<symbol>₹|\brs(?![a-z])\.?|\binr(?![a-z]))\s*|(?<![\w.$€£]))"
    rf"(?P<number>\d+(?:,\d+)*(?:\.\d+)?|(?:{SPOKEN})\b(?:[- ](?:{SPOKEN})\b)?)"
    r"(?:\s*(?P<unit>lakhs?|lacs?|crores?|cr|million|mn|thousand|l|m|k)\b)?"
    r"(?P<word>\s*(?:rupees|inr)\b)?", re.I)

EXPLICIT_BEFORE = re.compile(r"\b(?:budget|earmark\w*|set aside|allocat\w*|sanction\w*)\b", re.I)
EXPLICIT_AFTER = re.compile(r"^\s*(?:research |total )?budget\b", re.I)
OTHER_BEFORE = re.compile(
    r"\b(?:turnover|revenues?|sales|valuation|valued|profits?|market|costs?|costing|priced?|prices|savings?|saves?"
    r"|saving|loss(?:es)?|fined?|penalt\w+|raised|exports?|capacity|produc\w+|sells?|selling|worth)\b", re.I)
OTHER_AFTER = re.compile(
    r"^\s*(?:(?:per\s+|/\s*)(?!(?:year|annum|yr)\b)\w"
    r"|(?:company|business|group|firm|turnover|revenue|market|plant)\b|(?:in|of) (?:revenue|turnover|sales)\b)", re.I)
BUDGET_AFTER = re.compile(
    r"^\s*(?:$|[.,;:!?)]|(?:to|for|and|budget|research|available|grant|funding|per|over|on)\b)", re.I)
SPEND_BEFORE = re.compile(r"\b(?:have|has|fund\w*|spend\w*|invest\w*|commit\w*|up to|grant|sponsor\w*|offer\w*)\b", re.I)
RANGE = re.compile(r"^\s*(?:-|–|—|to|or)\s*$", re.I)
FOREIGN = re.compile(r"(?:[$€£]|\b(?:usd|eur|gbp)\b)\s*\d|\d\s*(?:dollars|euros|pounds sterling)\b", re.I)
SMALLEST = 10000


def number(raw):
    if raw[0].isdigit():
        return float(raw.replace(",", ""))
    parts = [WORDS[w] for w in re.split(r"[- ]", raw.lower())]
    return parts[0] * parts[1] if len(parts) == 2 and parts[1] == 100 else sum(parts)


def find(text):
    found = []
    for m in AMOUNT.finditer(text):
        unit = (m["unit"] or "").lower()
        scale = (1e5 if unit.startswith(("la", "l")) else 1e7 if unit.startswith("cr") else
                 1e6 if unit in ("million", "mn", "m") else 1e3 if unit in ("thousand", "k") else 1)
        before = re.split(r"[,;!?](?:\s|$)|\.\s|\b(?:and|with|while|but)\b", text[:m.start()])[-1][-70:]
        after = text[m.end():]
        explicit = bool(EXPLICIT_BEFORE.search(before) or EXPLICIT_AFTER.search(after))
        marked = bool(m["symbol"] or m["word"])
        amount = round(number(m["number"]) * scale)
        if marked:
            is_money = True
        elif unit.startswith(("lakh", "lac", "cr")):
            # "20 lakh tonnes" and "2 crore customers" are counts, not money.
            is_money = bool(BUDGET_AFTER.search(after)) and (
                explicit or bool(SPEND_BEFORE.search(before)) or not before.strip())
        elif unit:
            is_money = explicit and bool(BUDGET_AFTER.search(after))
        else:
            is_money = explicit and amount >= SMALLEST and bool(BUDGET_AFTER.search(after))
        other = bool(OTHER_AFTER.search(after)) or (not explicit and bool(OTHER_BEFORE.search(before)))
        found.append({"start": m.start(), "end": m.end(), "amount": amount, "money": is_money, "other": other,
                      "explicit": explicit})
    return found


def read(text):
    """Return (rupees, note). Rupees is None when there is no single clear budget."""
    found = find(text)
    for left, right in zip(found, found[1:]):
        gap = text[left["end"]:right["start"]]
        between = gap.strip().lower() == "and" and re.search(r"\bbetween\W*$", text[:left["start"]], re.I)
        if (RANGE.match(gap) or between) and any(a["money"] and not a["other"] for a in (left, right)):
            return None, "The budget is a range or a choice. State one ceiling in rupees."
    usable = [a for a in found if a["money"] and not a["other"]]
    chosen = [a for a in usable if a["explicit"]] or usable
    values = sorted({a["amount"] for a in chosen})
    if len(values) > 1:
        shown = ", ".join(f"₹{v:,}" for v in values)
        return None, f"Cannot tell which amount is the budget ({shown}). State one budget in rupees."
    if not values:
        if FOREIGN.search(text):
            return None, "The amount is not in rupees. It was not converted. State the budget in rupees."
        return None, "No clear budget in rupees was given, so milestones show percentages only."
    if values[0] < SMALLEST:
        return None, f"₹{values[0]:,} is too small to be a research budget. Check the amount and its unit."
    return values[0], None


def hide(text):
    """Replace every sum of money, so the amount cannot steer the search for labs."""
    for a in reversed([a for a in find(text) if a["money"]]):
        text = f"{text[:a['start']]} [budget] {text[a['end']:]}"
    return text
