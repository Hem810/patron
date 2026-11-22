import os

BASE = "https://api.crustdata.com"


def enabled():
    return bool(os.environ.get("CRUSTDATA_API_KEY"))


def post(client, op, path, body, credits):
    headers = {"Authorization": f"Bearer {os.environ['CRUSTDATA_API_KEY']}", "x-api-version": "2025-11-01"}
    return client.request("crustdata", op, BASE + path, body=body, headers=headers, credits=credits, timeout=45)


def identify(client, name):
    body, at = post(client, "company identify", "/company/identify", {"names": [name]}, 0.2)
    found = (body[0].get("matches") if body else None) or []
    out = []
    for match in sorted(found, key=lambda m: -(m.get("confidence_score") or 0))[:3]:
        data = match.get("company_data") or {}
        info = data.get("basic_info") or {}
        out.append({"id": data.get("crustdata_company_id"), "name": info.get("name"),
                    "confidence": match.get("confidence_score")})
    return out, at


def search(client, query):
    # No location: with "IN" the snippets and dates come back in mixed languages.
    body, at = post(client, "web search", "/web/search/live", {"query": query, "sources": ["web"]}, 1)
    if not body.get("success", True):
        return None, at
    return body.get("results") or [], at


def fetch(client, urls):
    body, at = post(client, "web fetch", "/web/enrich/live", {"urls": urls}, len(urls))
    return [(url, page.get("content") if page.get("success") else None) for url, page in zip(urls, body)], at
