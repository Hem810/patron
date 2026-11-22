"""The finished work: proposal, milestones, budget and draft agreement. Templates only, no model-written facts."""
import html

from .text import digest

CSS = """body{font:15px/1.55 -apple-system,Segoe UI,sans-serif;max-width:820px;margin:40px auto;padding:0 20px;color:#17211c}
h1{line-height:1.15}h2{margin-top:30px;border-bottom:1px solid #cbd5ce;padding-bottom:4px}
table{border-collapse:collapse;width:100%}td,th{text-align:left;vertical-align:top;padding:7px;border-bottom:1px solid #e2e8e4}
.note{background:#fff6dc;padding:10px 14px}.quote{color:#4c5b53}a{color:#14634a;overflow-wrap:anywhere}"""

STATUS = {"link_found": "Public link found", "lead_only": "Possible link, not confirmed",
          "none_found": "No public link found", "not_checked": "Not checked"}


def inr(value):
    if value is None:
        return "To be agreed"
    digits, out = str(int(value)), ""
    digits, out = digits[:-3], digits[-3:]
    while digits:
        digits, out = digits[:-2], f"{digits[-2:]},{out}"
    return f"₹{out}"


def money(total, rules):
    if total is None:
        research = overhead = None
    else:
        research = round(total * 100 / (100 + rules["overhead_pct_on_research"]))
        overhead = total - research
    rows, left = [], total
    for i, m in enumerate(rules["milestones"]):
        amount = None
        if total is not None:
            amount = left if i == len(rules["milestones"]) - 1 else round(total * m["pct"] / 100)
            left -= amount
        rows.append({**m, "amount": amount})
    return {"total": total, "research": research, "overhead": overhead, "milestones": rows}


def build(brief, ranked, rival_check, decision, cfg, unknowns):
    by_key = {lab["key"]: lab for lab in ranked["labs"]}
    pick = by_key[decision["pick"]]
    rules = cfg["agreement"]
    body = {
        "brief": brief, "lab": pick, "backups": [by_key[k] for k in decision["backups"]], "decision": decision,
        "budget": money(brief["budget_inr"], rules),
        "checks": [c for c in rival_check["checks"] if c["lab"] == pick["key"]],
        "links": [x for x in rival_check["links"] if x["lab"] == pick["key"]],
        "industry": [x for x in rival_check.get("industry", []) if x["lab"] == pick["key"]],
        "unknowns": unknowns, "agreement": rules,
    }
    body["sha"] = digest(body)
    return body


def link(url, label):
    if not str(url).startswith(("https://", "http://")):
        return html.escape(label)
    return f'<a href="{html.escape(url)}">{html.escape(label)}</a>'


def render(p):
    e = lambda value: html.escape(str(value if value is not None else ""))
    lab, b, rules, brief = p["lab"], p["budget"], p["agreement"], p["brief"]
    sponsor = brief["client"] or "[Sponsor legal name]"
    items = lambda values: "".join(f"<li>{e(v)}</li>" for v in values)

    papers = "".join(
        f"<tr><td>{link(x['url'], x['title'])}<div class=quote>{e(x['passage'])}</div>"
        f"{link(x['record_url'], 'Record: ' + x['field'])}</td>"
        f"<td>{e(x['date'])}</td><td>{e(x['retrieved_at'][:10])}</td></tr>" for x in lab["papers"])
    checks = "".join(f"<li><b>{e(c['rival'])}</b>: {STATUS[c['status']]} "
                     f"(checked {e(c['checked_at'][:10])})</li>" for c in p["checks"]) \
        or "<li>Not checked: no competitor was named.</li>"
    links = "".join(
        f"<li>{e(x['strength'].title())}, {e(x['scope'])} level: <span class=quote>{e(x['passage'])}</span> "
        f"({link(x['url'], x['source'])}, {e(x['date'] or 'date not stated')})</li>" for x in p["links"])
    stones = "".join(f"<tr><td>Month {m['month']}</td><td>{e(m['deliverable'])}</td><td>{m['pct']}%</td>"
                     f"<td>{inr(m['amount'])}</td></tr>" for m in b["milestones"])
    ties = "".join(
        f"<li><span class=quote>{e(x['passage'])}</span> "
        f"({link(x['url'], x['source'])}, {e(x['date'] or 'date not stated')})</li>" for x in p.get("industry", []))
    if ties:
        ties = f"<h2>Other industry work reported at this institute</h2><ul>{ties}</ul>"
    backups = "".join(f"<li><b>{e(x['name'])}</b>, {e(x['institution'])}. {e(p['decision']['why_not'][x['key']])}</li>"
                      for x in p["backups"]) or "<li>No other lab met the evidence bar.</li>"

    return f"""<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Research sponsorship proposal</title>
<style>{CSS}</style>
<p>Research sponsorship proposal, packet {p['sha'][:12]}</p>
<h1>{e(lab['name'])}, {e(lab['institution'])}</h1>
<p>For {e(sponsor)}. Problem: {e(brief['problem'])}</p>
<p class=note>Draft for human review. A public-record match does not establish capacity, willingness or the absence
of private agreements.</p>
<h2>Why this lab</h2>
<ul>{items(p['decision']['reasons'])}</ul>
<p>Evidence confidence: {e(p['decision']['confidence'])}. Affiliation as printed on the paper dated
{e(lab['affiliation']['date'])}: {link(lab['affiliation']['url'], lab['affiliation']['text'])}</p>
<table><tr><th>Evidence and exact field</th><th>Published</th><th>Retrieved</th></tr>{papers}</table>
<h2>Competitor check</h2><ul>{checks}{links}</ul>
{ties}<h2>Alternatives</h2><ul>{backups}</ul>
<h2>Budget</h2>
<table><tr><td>Total, excluding taxes</td><td>{inr(b['total'])}</td></tr>
<tr><td>Research</td><td>{inr(b['research'])}</td></tr>
<tr><td>Institute overhead ({rules['overhead_pct_on_research']}% of research)</td><td>{inr(b['overhead'])}</td></tr></table>
<p>{e(rules['overhead_basis'])} {link(rules['overhead_url'], 'Source')}</p>
<h2>Milestones</h2>
<table><tr><th>Due</th><th>Deliverable</th><th>Share</th><th>Payment</th></tr>{stones}</table>
<h2>Draft sponsored research agreement</h2>
<p>Between {e(sponsor)} (Sponsor) and {e(lab['institution'])} (Institute), with {e(lab['name'])} proposed as
Principal Investigator. Not binding until the authorised signatories of both parties sign.</p>
<ol>
<li><b>Scope.</b> The Institute will research the following problem: {e(brief['problem'])}</li>
<li><b>Term and payment.</b> Twelve months from signature. Each milestone above is paid after written acceptance,
except the first, which is paid on signature. Taxes are additional.</li>
<li><b>Principal Investigator.</b> If the Principal Investigator becomes unavailable, the Institute proposes a
replacement within 30 days. The Sponsor may accept, or end the agreement and pay for work completed.</li>
<li><b>Intellectual property.</b> Each party keeps what it brought. Results are jointly owned unless both agree
otherwise in writing. The Sponsor has six months from each disclosure to negotiate a licence.</li>
<li><b>Publication.</b> The Institute may publish after giving the Sponsor {rules['publication_review_days']} days
to ask for removal of its confidential information or time to file a patent.</li>
<li><b>Other sponsors.</b> The Institute discloses in writing any active project on this problem with another
company, without breaching that company's confidentiality, and keeps the Sponsor's information separate.</li>
<li><b>Confidentiality and data.</b> Confidential information is protected for three years. Personal data is limited
to what the project needs.</li>
<li><b>Integrity.</b> The Sponsor cannot direct findings or block publication of unfavourable results. Funding is
acknowledged in every publication.</li>
<li><b>Termination.</b> Either party may end with 60 days' notice. Work completed and non-cancellable costs are paid.</li>
<li><b>Law and disputes.</b> Indian law. Thirty days of negotiation, then arbitration at a seat both parties agree.</li>
</ol>
<p>Sponsor signatory: ____________________ Date: ________</p>
<p>Institute signatory: ____________________ Date: ________</p>
<h2>Ask before signing</h2><ul>{items(p['decision']['questions'])}</ul>
<h2>What could not be verified</h2><ul>{items(p['unknowns'])}</ul>
</html>"""
