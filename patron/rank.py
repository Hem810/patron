"""Deterministic lab ranking. Citation counts and prestige are deliberately not inputs."""
from collections import defaultdict
from datetime import date

from . import identity
from .text import stems


def appearances(papers, country):
    for paper in papers:
        last = len(paper["authors"]) - 1
        for position, author in enumerate(paper["authors"]):
            if not author["family"]:
                continue
            for affiliation in author["affiliations"]:
                if not identity.in_country(affiliation, country):
                    continue
                place = identity.institution(affiliation)
                if place:
                    yield {"paper": paper, "author": author, "place": place, "affiliation": affiliation,
                           "printed": True, "lead": position == last and last > 0}
                    break
            else:
                joined = author.get("joined")
                if joined:
                    yield {"paper": paper, "author": author, "place": joined["place"], "printed": False,
                           "affiliation": f"Affiliation not printed. Joined by {joined['basis']}.",
                           "lead": position == last and last > 0}


def group_people(rows):
    """Join on ORCID, or on an unambiguous name at one institution. Never on name alone."""
    by_name = defaultdict(set)
    full_names = defaultdict(set)
    for r in rows:
        a = r["author"]
        key = (identity.name_key(a["given"], a["family"]), r["place"])
        if a["orcid"]:
            by_name[key].add(a["orcid"])
        if any(len(w) > 1 for w in a["given"].replace(".", " ").split()):
            full_names[(identity.initials_key(a["given"], a["family"]), r["place"])].add(key[0])
    groups = defaultdict(list)
    for r in rows:
        a = r["author"]
        name = identity.name_key(a["given"], a["family"])
        if not any(len(w) > 1 for w in a["given"].replace(".", " ").split()):
            options = full_names[(identity.initials_key(a["given"], a["family"]), r["place"])]
            if len(options) == 1:
                name = next(iter(options))
        known = by_name[(name, r["place"])]
        if a["orcid"]:
            person = "orcid:" + a["orcid"]
        elif len(known) == 1:
            person = "orcid:" + next(iter(known))
        else:
            person = f"name:{name}|{r['place']}"
        groups[person].append(r)
    return groups


def covers(titles, group):
    for title in titles:
        have = stems(title)
        for term in group:
            if stems(term) <= have:
                return True
    return False


def rank(papers, screened, cfg, today=None, essentials=(), keep=8):
    today = today or date.today()
    rules = cfg["ranking"]
    wanted = set(screened["relevant"])
    relevant = [p for p in papers if p["id"] in wanted and not p["retracted"]]
    groups = group_people(list(appearances(relevant, cfg["country"])))
    cutoff = f"{today.year - rules['recent_years']}-{today.month:02d}"

    homes = defaultdict(set)
    for rows in groups.values():
        a = max((r["author"] for r in rows), key=lambda x: len(x["given"]))
        homes[identity.name_key(a["given"], a["family"])].update(r["place"] for r in rows)

    labs, rejected = [], 0
    # The field must evidence every essential subject. A single lab need only cover one of them.
    uncovered = [g[0] for g in essentials if not covers([p["title"] for p in relevant], g)]
    if uncovered:
        return {"labs": [], "relevant_papers": len(relevant), "people_below_bar": len(groups), "uncovered": uncovered}
    for key, rows in groups.items():
        unique = {r["paper"]["id"]: r for r in rows}
        rows = sorted(unique.values(), key=lambda r: (r["paper"]["date"] or "", r["paper"]["id"]), reverse=True)
        counts = {
            "fit": len(rows),
            "lead": sum(r["lead"] for r in rows),
            "recent": sum((r["paper"]["date"] or "") >= cutoff for r in rows),
            "grants": sum(bool(r["paper"]["funders"]) for r in rows),
            "industry": sum(any(identity.is_company(a) for x in r["paper"]["authors"] for a in x["affiliations"])
                            for r in rows),
        }
        if counts["fit"] < rules["min_papers"] or counts["lead"] < rules["min_lead_papers"]:
            rejected += 1
            continue
        if essentials and not any(covers([r["paper"]["title"] for r in rows], g) for g in essentials):
            rejected += 1
            continue
        parts = {k: round(w * min(1, counts[k] / rules["saturate"][k]), 1) for k, w in rules["weights"].items()}
        best = max((r["author"] for r in rows), key=lambda a: len(a["given"]))
        name = f"{best['given']} {best['family']}".strip()
        cautions = []
        others = homes[identity.name_key(best["given"], best["family"])] - {r["place"] for r in rows}
        if others:
            cautions.append(f"A researcher with the same name appears at {', '.join(sorted(others))}. Not merged.")
        if not key.startswith("orcid:"):
            cautions.append("No ORCID on these papers. Identity rests on name plus institution.")
        printed = [r for r in rows if r["printed"]]
        if len(printed) < len(rows):
            cautions.append(f"{len(rows) - len(printed)} of {len(rows)} papers print no affiliation "
                            "and were joined by ORCID or a shared co-author.")
        if counts["recent"] == 0:
            cautions.append("No matching paper in the recent window. Confirm the lab still works on this.")
        labs.append({
            "key": key, "name": name, "institution": rows[0]["place"],
            "orcid": key.split(":", 1)[1] if key.startswith("orcid:") else None,
            "score": round(sum(parts.values()), 1), "parts": parts, "counts": counts, "cautions": cautions,
            "affiliation": {"text": (printed or rows)[0]["affiliation"], "date": (printed or rows)[0]["paper"]["date"],
                            "url": (printed or rows)[0]["paper"]["record_url"]},
            "papers": [{
                "id": r["paper"]["id"], "title": r["paper"]["title"], "date": r["paper"]["date"],
                "url": r["paper"]["url"], "record_url": r["paper"]["record_url"], "lead": r["lead"],
                "field": "author[].affiliation[].name" if r["printed"] else "author[] name, ORCID and co-authors",
                "passage": r["affiliation"],
                "funders": r["paper"]["funders"], "retrieved_at": r["paper"]["retrieved_at"],
                "sha256": r["paper"]["sha256"],
            } for r in rows],
        })
    labs.sort(key=lambda x: (-x["score"], -x["counts"]["lead"], -x["counts"]["fit"], x["name"], x["key"]))
    return {"labs": labs[:keep], "relevant_papers": len(relevant), "people_below_bar": rejected,
            "uncovered": uncovered}
