"""Spike R5: do CQL2 filters in Collection Search work on top-level fields of collections?"""
import json, sys
import requests

BASE = "http://127.0.0.1:8080"
# Adjust these field names to the draft schema
S, R, U = "health:status", "health:representation_type", "health:update_frequency"

def make(cid, status, rep, freq, kw):
    """Build a minimal test collection with three health fields."""
    return {"type": "Collection", "stac_version": "1.0.0", "id": cid, "title": cid, "stac_extensions": ["https://vitalstac.github.io/health/v0.1.0/schema.json"],
            "description": "Spike " + cid, "license": "CC0-1.0", "keywords": kw,
            S: status, R: rep, U: freq,
            "extent": {"spatial": {"bbox": [[5.9, 50.3, 9.5, 52.5]]},
                       "temporal": {"interval": [["2020-01-01T00:00:00Z", None]]}},
            "links": []}

COLLS = [make("spike-a", "ongoing", "raster", "daily", ["air", "pm25"]),
         make("spike-b", "completed", "vector", "asNeeded", ["facilities"]),
         make("spike-c", "ongoing", "timeSeries", "weekly", ["influenza"])]

def txt(f): return {"filter": f, "filter-lang": "cql2-text"}
def js(o): return {"filter": json.dumps(o), "filter-lang": "cql2-json"}

TESTS = [
    ("Equality (text)", txt(f'"{S}" = \'ongoing\''), {"spike-a", "spike-c"}),
    ("Equality (json)", js({"op": "=", "args": [{"property": S}, "completed"]}), {"spike-b"}),
    ("AND (text)", txt(f'"{S}" = \'ongoing\' AND "{R}" = \'raster\''), {"spike-a"}),
    ("OR (text)", txt(f'"{R}" = \'vector\' OR "{R}" = \'timeSeries\''), {"spike-b", "spike-c"}),
    ("No match", txt(f'"{S}" = \'unknown\''), set()),
    ("Free text q", {"q": "influenza"}, {"spike-c"}),
    ("IN (optional)", txt(f'"{R}" IN (\'vector\', \'raster\')'), {"spike-a", "spike-b"}),
]

def ids(params):
    """Run a Collection Search and return the matching spike collection IDs (or an error text)."""
    r = requests.get(BASE + "/collections", params=params, timeout=30)
    if r.status_code != 200:
        return "HTTP %d: %s" % (r.status_code, r.text[:150])
    return {c["id"] for c in r.json()["collections"] if c["id"].startswith("spike-")}

# Setup: delete old test collections (if any) and create them again
for c in COLLS:
    requests.delete(f"{BASE}/collections/{c['id']}", timeout=30)
    print("POST", c["id"], requests.post(f"{BASE}/collections", json=c, timeout=30).status_code)

print("Queryables:", sorted(requests.get(BASE + "/queryables", timeout=30).json().get("properties", {})))

# Run the tests
for name, params, expected in TESTS:
    got = ids(params)
    shown = sorted(got) if isinstance(got, set) else got
    print(("PASS " if got == expected else "FAIL ") + name, "| expected", sorted(expected), "| got", shown)


if "--cleanup" in sys.argv:
    for c in COLLS:
        requests.delete(f"{BASE}/collections/{c['id']}", timeout=30)