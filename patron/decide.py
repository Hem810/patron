"""Explainable choice among ranked labs."""
from datetime import date

LABELS = {"fit": "on-topic papers", "lead": "papers as last author", "recent": "recent papers",
          "grants": "papers naming a grant", "industry": "papers with company co-authors"}


def counted(number, key):
    label = LABELS[key]
    return f"{number} {label.replace('papers', 'paper', 1) if number == 1 else label}"


def decide(ranked, rival_check, cfg, chosen_key=None):
    labs = ranked["labs"][: cfg["rivals"]["labs_checked"]]
    if not labs:
        return None
    since = str(date.today().year - cfg["years"])

    def personal(lab):
        return sorted({x["rival"] for x in rival_check["links"]
                       if x["lab"] == lab["key"] and x["strength"] == "confirmed" and x["scope"] == "person"
                       and (not x["date"] or x["date"][:4] >= since)})

    clear = [lab for lab in labs if not personal(lab)]
    pick = next((lab for lab in labs if lab["key"] == chosen_key), None) or (clear or labs)[0]
    others = [lab for lab in labs if lab["key"] != pick["key"]]
    others.sort(key=lambda lab: bool(personal(lab)))

    reasons = [counted(pick["counts"][k], k) for k in LABELS if pick["counts"][k]]
    if chosen_key:
        reasons.insert(0, "chosen by the approver instead of the first recommendation")
    elif pick["key"] != labs[0]["key"]:
        reasons.insert(0, f"{labs[0]['name']} scored higher but has a direct public link to "
                          f"{', '.join(personal(labs[0]))}, so ask them before funding")

    margin = cfg["ranking"]["close_call_points"]
    close = [lab for lab in others if not personal(lab) and abs(pick["score"] - lab["score"]) <= margin]
    why_not = {}
    for lab in others:
        if lab in close:
            why_not[lab["key"]] = (f"Too close to call ({lab['score']} against {pick['score']}). "
                                   "Speak to both before funding.")
            continue
        linked = personal(lab)
        if linked:
            why_not[lab["key"]] = f"Direct public link to {', '.join(linked)}. A question to ask, not proof of a conflict."
            continue
        behind = [f"{LABELS[k]} ({lab['counts'][k]} against {pick['counts'][k]})"
                  for k in LABELS if lab["parts"][k] < pick["parts"][k]]
        why_not[lab["key"]] = ("Fewer " + " and ".join(behind[:2]) + ".") if behind \
            else "Close on this evidence. A reasonable alternative."

    questions = [f"{lab['name']} at {lab['institution']} is within {margin} points of this choice. "
                 "Speak to both before funding." for lab in close]
    for link in rival_check["links"]:
        if link["lab"] != pick["key"]:
            continue
        verb = "has a public link to" if link["strength"] == "confirmed" else "came up in an unconfirmed search match with"
        who = pick["name"] if link["scope"] == "person" else pick["institution"]
        questions.append(f"{who} {verb} {link['rival']}. Ask about active projects, overlap and confidentiality.")
    if any(x["lab"] == pick["key"] for x in rival_check.get("industry", [])):
        questions.append(f"{pick['institution']} has other reported industry work. "
                         "Ask whether it overlaps this problem, who funds it and who owns the results.")
    questions += [f"Does {pick['name']} still lead this work at {pick['institution']}, with capacity for 12 months?",
                  "Is any part of this problem already funded, patented or promised to another sponsor?"]

    thin = pick["counts"]["fit"] < 4 or not pick["orcid"]
    return {"pick": pick["key"], "backups": [lab["key"] for lab in others[:2]], "reasons": reasons,
            "why_not": why_not, "questions": list(dict.fromkeys(questions)),
            "confidence": "limited" if thin else "close call" if close else "good", "overridden": bool(chosen_key)}
