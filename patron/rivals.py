"""Public links between shortlisted labs and named competitors.

confirmed: one sentence, or one paper record, states the link itself.
lead:      both are mentioned, but no single passage states the link. Never treated as a fact.
"""
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from . import crustdata, identity, papers
from .net import SourceError
from .text import clean, digest, fold, mentions, now, stems

NEWS = "https://news.google.com/rss/search"
RELATION = re.compile(
    r"collaborat|partner|\bmou\b|memorandum|testbed|test bed|\bfund(?:s|ed|ing)?\b|sponsor|\bjointly\b"
    r"|\bjoint (?:research|project|centre|center|study|development)|in association with|working together"
    r"|agreement|tie[ -]?up|ties up|teams? up|pilot|plant trial|research (?:chair|centre|center)", re.I)
NEGATION = re.compile(r"\b(?:no|not|denies|denied|ends|ended|terminat\w+|without|cancel\w*)\b", re.I)
MAX_SENTENCE = 360
COMPANY_HINT = re.compile(
    r"\b(?:Cements?|Ltd|Limited|Industries|Motors|Steel|Energy|Pharma\w*|Corporation|Corp|Inc|Pvt|Batteries"
    r"|Petroleum|Chemicals|Labs|Technologies|Textiles|Mills)\b")
PUBLISHED = re.compile(r"article:published_time[\"'][^>]*content=[\"'](\d{4}-\d\d-\d\d)")
CANONICAL = re.compile(r"<link[^>]+rel=[\"']canonical[\"'][^>]*href=[\"'](https?://[^\"']+)")
RESEARCH_BODY = re.compile(
    r"\bIIT(?:[ -](?!and\b)[A-Z][a-z]+)?|\bIISc\b|\bBITS Pilani\b|\bNIT [A-Z][a-z]+|\bCSIR(?:-[A-Z]+)?\b"
    r"|\bIISER\b|Indian Institute of (?:Technology|Science)")
SECTORS = ("cement", "steel", "motors")
GENERIC = {"cement", "industries", "limited", "ltd", "batteries", "battery", "steel", "motors", "energy"}


def rival_names(rival):
    words = rival.split()
    names = [rival] + ([] if rival.lower().endswith("s") else [rival + "s"])
    short = re.sub(r"[,.]?\s+(?:Ltd|Limited)\.?$", "", rival, flags=re.I)
    if short != rival:
        names.append(short)
    # 'UltraTech Cement' may be printed as 'UltraTech'. 'Tata Steel' must never shrink to 'Tata'.
    if len(words) == 2 and words[1].lower() in GENERIC and len(words[0]) >= 7:
        names.append(words[0])
    return names


def place_names(place):
    names = [place]
    if place.startswith("IIT "):
        city = place[4:]
        names.append(f"Indian Institute of Technology {city}")
        names.append(f"Indian Institute of Technology ({city})")
        if city == "Delhi":
            names.append("IITD")
    elif place.startswith("BITS Pilani"):
        names.append(place.replace("BITS Pilani", "Birla Institute of Technology and Science Pilani"))
    elif place == "IISc Bangalore":
        names += ["IISc", "Indian Institute of Science Bengaluru"]
    return names


def any_named(text, names):
    return any(mentions(text, n) for n in names)


def sentences(text):
    # Search snippets join unrelated fragments with ellipses, bullets and pipes. Those are boundaries too.
    parts = re.split(r"(?<=[.!?])(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<!\bProf\.)(?<!\bShri\.)(?<!\b[A-Z]\.)"
                     r"\s+(?=[A-Z])|\n+|\.\.\.|\u2026|\s[\u00b7\u2022|]\s|;\s", text)
    return [s for s in (part.strip(" .") for part in parts) if s]


def read_passage(text, lab, rival):
    """Strength of one source text as evidence, with the passage that supports it."""
    lead = None
    for sentence in sentences(text):
        if len(sentence) > MAX_SENTENCE:  # longer runs are tag lists and menus, where co-occurrence means nothing
            continue
        if any_named(sentence, rival_names(rival)) and any_named(sentence, place_names(lab["institution"])):
            if RELATION.search(sentence) and not NEGATION.search(sentence):
                return "confirmed", sentence[:420], "person" if mentions(sentence, lab["name"]) else "institution"
            lead = lead or sentence[:420]
    return ("lead", lead, "institution") if lead else (None, None, None)


def evidence(lab, rival, strength, scope, source, url, field, passage, day, at):
    return {"id": "L" + digest([lab["key"], rival, url, passage])[:10], "lab": lab["key"], "rival": rival,
            "strength": strength, "scope": scope, "source": source, "url": url, "field": field,
            "passage": passage, "date": day, "retrieved_at": at, "sha256": digest(passage)}


def from_papers(paper, labs, rival):
    funders = [f for f in paper["funders"] if any_named(f, rival_names(rival))]
    staff = [a for x in paper["authors"] for a in x["affiliations"]
             if any_named(a, rival_names(rival)) and identity.is_company(a + " ltd")]
    if not funders and not staff:
        return []
    out = []
    for lab in labs:
        scope = None
        for author in paper["authors"]:
            here = any(identity.institution(a) == lab["institution"] for a in author["affiliations"])
            if not here:
                continue
            same = (lab["orcid"] and author["orcid"] == lab["orcid"]) or (
                identity.name_key(author["given"], author["family"]) == fold(lab["name"]))
            scope = "person" if same else (scope or "institution")
        if scope:
            field = "funder[].name" if funders else "author[].affiliation[].name"
            out.append(evidence(lab, rival, "confirmed", scope, "Crossref paper record", paper["record_url"],
                                field, (funders or staff)[0], paper["date"], paper["retrieved_at"]))
    return out


def joint_papers(client, brief, rival):
    body, at = client.request("crossref", "competitor co-authorship", papers.API, params={
        "query.affiliation": rival, "query.bibliographic": brief["phrases"][0],
        "filter": f"from-pub-date:{papers.window(client.cfg)}", "rows": 50, "select": papers.SELECT,
    }, timeout=20)
    return [r for r in (papers.record(i, at) for i in body["message"]["items"]) if r]


def news_day(value):
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def from_news(client, lab, rival, topic):
    query = f'"{rival_names(rival)[-1]}" "{lab["institution"]}"'
    raw, at = client.request("news", "announcement search", NEWS,
                             params={"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
                             timeout=15, parse="text")
    try:
        items = ET.fromstring(raw).findall(".//item")
    except ET.ParseError as err:
        raise SourceError("news: unreadable response") from err
    out = []
    for item in items[:15]:
        title = clean(item.findtext("title")).rsplit(" - ", 1)[0]
        day = news_day(item.findtext("pubDate"))
        strength, passage, scope = read_passage(title, lab, rival)
        # The search matched both names in the article. The headline must still name the competitor to count as a lead.
        if not strength and RELATION.search(title) and any_named(title, rival_names(rival)) and (
                identity.ACADEMIC.search(title) or (topic - stems(rival)) & stems(title)):
            strength, passage, scope = "lead", title, "institution"
        if strength:
            out.append(evidence(lab, rival, strength, scope, "News headline", item.findtext("link") or "",
                                "item.title", passage, day, at))
    out.sort(key=lambda e: (e["strength"] == "confirmed", e["date"] or ""), reverse=True)
    return out[:2], []


def snippet_day(snippet, retrieved=None):
    ago = re.match(r"\s*(\d{1,2}) (minute|hour|day|week)s? ago\b", snippet or "")
    if ago and retrieved:
        step = timedelta(**{ago.group(2) + "s": int(ago.group(1))})
        return (datetime.fromisoformat(retrieved) - step).date().isoformat()
    found = re.match(r"\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\b", snippet or "")
    try:
        return datetime.strptime(found.group(1), "%b %d, %Y").date().isoformat() if found else None
    except ValueError:
        return None


def company_key(name):
    return re.sub(r"( (?:ltd|limited|pvt|private|india))+$", "", fold(name))


def best_match(given, matches):
    """One company, or none. A tie on confidence is settled only by a unique exact name."""
    if not matches or (matches[0]["confidence"] or 0) < 0.8:
        return None
    top = [m for m in matches if m["confidence"] == matches[0]["confidence"]]
    exact = [m for m in top if company_key(m["name"]) == company_key(given)]
    if len(exact) == 1:
        return exact[0]
    # A lone top score is trusted only if it carries the name the customer used.
    return top[0] if len(top) == 1 and mentions(top[0]["name"], given) else None


def resolve(client, brief, request=""):
    """Map each competitor to one company and check a company named twice only once."""
    given = brief["rivals"]
    if not crustdata.enabled() or not given:
        return [{"name": n, "search": n, "identity": "not_checked"} for n in given], [], []
    sector = next((w for w in SECTORS if mentions(request + " " + brief.get("problem", ""), w)), None)
    records, notes, keep, seen = [], [], [], set()
    for name in given:
        match, asked, matches = None, name, []
        try:
            matches, at = crustdata.identify(client, name)
            match = best_match(name, matches)
            if not match and sector and not mentions(name, sector):
                # 'UltraTech' alone matches five unrelated firms at full confidence. 'UltraTech Cement' matches one.
                asked = f"{name} {sector.title()}"
                matches, at = crustdata.identify(client, asked)
                match = best_match(asked, matches)
        except SourceError as err:
            notes.append(f"Company identity for {name} was not verified ({err}).")
        if match:
            if match["id"] in seen:
                notes.append(f"'{name}' is the same company as another name in the request. Checked once.")
                continue
            seen.add(match["id"])
            records.append({"given": name, "matched": match["name"], "id": match["id"], "asked": asked,
                            "confidence": match["confidence"], "retrieved_at": at})
            search = re.sub(r"[,.]? (?:Ltd|Limited)\.?$", "", match["name"])
        else:
            search = name
            could_be = ", ".join(dict.fromkeys(m["name"] for m in matches[:3] if m["name"]))
            hint = f" It could be {could_be}. Give the full legal name to settle it." if could_be else ""
            notes.append(f"Cannot verify which company '{name}' is.{hint} Searched by the name as given.")
        keep.append({"name": name, "search": search, "identity": "resolved" if match else "unresolved"})
    return keep, records, notes


def prefetch(client, brief, request):
    """Start the competitor-side calls early. check() gets the same responses from the job's cache."""
    names, _, _ = resolve(client, brief, request)
    web_searches(client, brief, names, [])


def short_topic(brief):
    groups = brief.get("essentials") or []
    if not groups:
        return brief["phrases"][0]
    head = groups[0][0]
    sector = next((w for w in SECTORS if mentions(brief.get("problem", ""), w) and not mentions(head, w)), "")
    return f"{head} {sector}".strip()


def web_searches(client, brief, names, labs):
    """One search from each competitor's side and one from each lab's side."""
    queries = [("rival", n["name"], f"{n['search']} IIT research partnership testbed") for n in names]
    queries += [("lab", lab["key"], f"{lab['institution']} {short_topic(brief)} industry pilot trial partner company")
                for lab in labs]
    if labs and short_topic(brief) != brief["phrases"][0]:  # the two wordings surface different pilots
        queries.append(("lab", labs[0]["key"],
                        f"{labs[0]['institution']} {brief['phrases'][0]} industry pilot trial partner company"))
    done, notes = [], []
    if not queries:
        return done, notes
    with ThreadPoolExecutor(6) as pool:
        for (kind, key, query), job in [(q, pool.submit(crustdata.search, client, q[2])) for q in queries]:
            try:
                results, at = job.result()
            except SourceError as err:
                results, at = None, None
                notes.append(f'Web search "{query}" was not completed ({err}).')
            if results is not None:
                done.append({"kind": kind, "key": key, "results": results[:10], "at": at})
    return done, notes


def worth_reading(searches, names, labs, topic, limit):
    """The proof is usually in the body of the page, so read the most promising ones."""
    places = {lab["key"]: place_names(lab["institution"]) for lab in labs}
    everyone = [alias for n in names for alias in rival_names(n["name"])]
    ranked = []
    for search in searches:
        wanted = rival_names(search["key"]) if search["kind"] == "rival" else places[search["key"]]
        best = None
        for position, item in enumerate(search["results"]):
            url, text = item.get("url") or "", clean(f"{item.get('title')}. {item.get('snippet')}")
            if not RELATION.search(text) or not url.startswith("http"):
                continue
            value = (2 * any_named(text, wanted) + 3 * bool(everyone and any_named(text, everyone))
                     + 2 * bool(identity.ACADEMIC.search(text)) + min(2, len(topic & stems(text)))
                     + 2 * ("google.com/goto" not in url) - position / 20)
            if not best or value > best[0]:
                best = (value, url)
        if best:
            ranked.append((search["kind"] == "rival", best[0], best[1]))
    ranked.sort(reverse=True)
    return list(dict.fromkeys(url for _, _, url in ranked))[:limit]


def page_text(content):
    """Readable text with one line per block, so menus and bylines cannot join onto a sentence."""
    content = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", content or "")
    blocks = re.split(r"(?i)</?(?:p|div|li|ul|ol|h[1-6]|br|td|tr|table|section|article|header|footer|nav|aside"
                      r"|figure|figcaption|blockquote|time|button)\b[^>]*>", content)
    return "\n".join(line for line in map(clean, blocks) if line)


def web_documents(client, searches, urls):
    docs, notes = [], []
    for search in searches:
        for item in search["results"]:
            snippet = clean(re.sub(r"Read more$", "", item.get("snippet") or ""))
            docs.append({"source": "Crustdata web search", "field": "results[].title + snippet", "at": search["at"],
                         "url": item.get("url") or "", "date": snippet_day(snippet, search["at"]), "search": search,
                         "text": f"{clean(item.get('title'))}. {snippet}"})
    if not urls:
        return docs, notes
    try:
        pages, at = crustdata.fetch(client, urls)
    except SourceError as err:
        return docs, [f"The most relevant announcement pages could not be read ({err})."]
    dates = {d["url"]: d["date"] for d in docs}
    for url, content in pages:
        body = page_text(content)
        if len(body) < 400:
            notes.append("One announcement page could not be opened, so only its search snippet was used.")
            continue
        day, canonical = PUBLISHED.search(content), CANONICAL.search(content)
        docs.append({"source": "Crustdata web fetch", "field": "page content", "at": at, "search": None,
                     "url": canonical.group(1) if canonical else url, "text": body,
                     "date": day.group(1) if day else dates.get(url)})
    return docs, notes


def web_links(docs, names, labs, topic):
    """Turn retrieved text into competitor links, plus industry ties the customer did not name."""
    links, industry = [], {}
    everyone = [alias for n in names for alias in rival_names(n["name"])]
    for lab in labs:
        places = place_names(lab["institution"])
        for rival in names:
            best = None
            for doc in docs:
                strength, passage, scope = read_passage(doc["text"], lab, rival["name"])
                if not strength and doc["search"] and doc["search"]["kind"] == "lab" \
                        and doc["search"]["key"] == lab["key"]:
                    # Found searching for this lab: names the competitor and a relationship, but not the lab itself.
                    for part in sentences(doc["text"]):
                        if len(part) <= MAX_SENTENCE and any_named(part, rival_names(rival["name"])) \
                                and RELATION.search(part) and topic & stems(doc["text"]):
                            strength, passage, scope = "lead", part, "institution"
                            break
                if not strength:
                    continue
                value = (strength == "confirmed", scope == "person", bool(doc["date"]), doc["date"] or "")
                if not best or value > best[0]:
                    best = (value, evidence(lab, rival["name"], strength, scope, doc["source"], doc["url"],
                                            doc["field"], passage, doc["date"], doc["at"]))
            if best:
                links.append(best[1])

        ties = {}
        for doc in docs:
            if not topic & stems(doc["text"]):
                continue
            for part in sentences(doc["text"]):
                if (len(part) <= MAX_SENTENCE and any_named(part, places) and RELATION.search(part)
                        and COMPANY_HINT.search(part) and not NEGATION.search(part)
                        and not (everyone and any_named(part, everyone))):
                    tie = evidence(lab, "", "reported", "institution", doc["source"], doc["url"], doc["field"], part,
                                   doc["date"], doc["at"])
                    if len(part) > len(ties.get(doc["url"], {}).get("passage", "")):
                        ties[doc["url"]] = tie
        industry[lab["key"]] = sorted(ties.values(), key=lambda e: e["date"] or "", reverse=True)[:2]
    return links, [tie for group in industry.values() for tie in group]


def rival_ties(docs, names, topic):
    """Research links each competitor has published, whether or not that institute was shortlisted."""
    out = []
    for rival in names:
        own, seen = [], set()
        for doc in sorted(docs, key=lambda d: not d["date"]):  # prefer the dated copy of a link
            if not topic & stems(doc["text"]):
                continue
            for part in sentences(doc["text"]):
                if len(part) > MAX_SENTENCE or NEGATION.search(part) or not RELATION.search(part):
                    continue
                if not any_named(part, rival_names(rival["name"])) or not RESEARCH_BODY.search(part):
                    continue
                body = RESEARCH_BODY.search(part).group(0).lower()
                if body in seen:
                    continue
                seen.add(body)
                own.append(evidence({"key": ""}, rival["name"], "reported", "competitor", doc["source"], doc["url"],
                                    doc["field"], part, doc["date"], doc["at"]))
        out += sorted(own, key=lambda e: e["date"] or "", reverse=True)[:3]
    return out


def check(client, brief, found, ranked, request=""):
    rules = client.cfg["rivals"]
    labs = ranked["labs"][: rules["labs_checked"]]
    names, companies, notes = resolve(client, brief, request)
    topic = {w for phrase in found.get("phrases") or brief["phrases"] for w in stems(phrase) if len(w) > 2}
    links, checks, industry, elsewhere = [], [], [], []

    for rival in names:
        pool = list(found["papers"])
        paper_ok = True
        try:
            pool += joint_papers(client, brief, rival["search"])
        except SourceError as err:
            paper_ok = False
            notes.append(f"Co-authorship search for {rival['name']} was not completed ({err}).")
        for paper in {p["doi"]: p for p in pool}.values():
            links += from_papers(paper, labs, rival["name"])
        for lab in labs:
            checks.append({"lab": lab["key"], "rival": rival["name"], "papers": paper_ok,
                           "announcements": False, "announcement_sources": [],
                           "identity": rival["identity"]})

    searched = set()
    if crustdata.enabled():
        searches, missed = web_searches(client, brief, names, labs)
        notes += missed
        searched = {(s["kind"], s["key"]) for s in searches}
        urls = worth_reading(searches, names, labs, topic, rules["max_page_fetches"])
        docs, unreadable = web_documents(client, searches, urls)
        notes += unreadable
        web, industry = web_links(docs, names, labs, topic)
        links += web
        elsewhere = rival_ties(docs, names, topic)
        for c in checks:
            c["announcements"] = ("rival", c["rival"]) in searched and ("lab", c["lab"]) in searched
            if c["announcements"]:
                c["announcement_sources"].append("Crustdata web search")

    # Headlines are the fallback, with no key or when a web search failed.
    by_key = {lab["key"]: lab for lab in labs}
    with ThreadPoolExecutor(4) as pool:
        jobs = [(c, pool.submit(from_news, client, by_key[c["lab"]], c["rival"], topic))
                for c in checks if not c["announcements"]]
        for c, job in jobs:
            try:
                found_links, _ = job.result()
            except SourceError as err:
                notes.append(f"Announcements for {by_key[c['lab']]['institution']} and {c['rival']}: not checked ({err}).")
                continue
            c["announcements"] = True
            c["announcement_sources"].append("Google News headlines")
            links += found_links

    unresolved = {rival["name"] for rival in names if rival["identity"] == "unresolved"}
    links = [{**item, "strength": "lead", "identity": "unresolved"}
             if item["rival"] in unresolved else item for item in links]
    for c in checks:
        mine = [x for x in links if x["lab"] == c["lab"] and x["rival"] == c["rival"]]
        c["status"] = ("link_found" if any(x["strength"] == "confirmed" for x in mine) else
                       "lead_only" if mine else
                       "none_found" if c["papers"] and c["announcements"] and c["identity"] != "unresolved"
                       else "not_checked")
        c["checked_at"] = now()
    unique = {x["id"]: x for x in links}
    return {"rivals": [n["name"] for n in names], "companies": companies, "links": list(unique.values()),
            "industry": industry, "elsewhere": elsewhere, "checks": checks, "notes": notes,
            "web_source": "web searches and pages" if searched else "news headlines"}
