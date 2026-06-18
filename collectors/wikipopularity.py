"""Wikipedia pageviews collector — the mainstream-recognition signal.

For each Pokémon character we cache 12 months of English-Wikipedia article views,
matched to that specific Pokémon's article. This is the price-INDEPENDENT
"how many people actually look it up" signal that popularity.py blends with the
2020 fan poll (see popularity.py for how the two combine).

Matching is careful because Pokémon names collide with everyday words and other
media (Golem the folklore creature, Volbeat the metal band, Electrode the
conductor). We:
  1. Prefer the unambiguous "<Name> (Pokémon)" article (resolving redirects to
     its canonical title).
  2. Else accept the bare "<Name>" article only if it's a real page (not a "List
     of Pokémon" redirect) AND carries a Pokémon category.
  3. Require the canonical title, stripped of " (Pokémon)", to equal the name —
     this drops shared-article aliases (Scream Tail -> Jigglypuff, Marowak ->
     Cubone, the Regis).

Run: ./.venv/bin/python -m collectors.wikipopularity
Writes data/wiki_pageviews.json. Wikipedia traffic moves slowly, so this only
needs an occasional refresh — it is NOT part of the daily run.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from pipeline import config, popularity

_UA = {"User-Agent": "PokeResearch/1.0 (educational analytics) wiki-popularity"}
_PV_WINDOW = ("2025060100", "2026053100")  # 12 full months; bump on refresh
_WIKI_OUT = config.ROOT / "data" / "wiki_pageviews.json" if hasattr(config, "ROOT") \
    else __import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "wiki_pageviews.json"


def _get(url):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _resolve(titles):
    """{input_title: (exists, canonical_title, categories_str)} for a batch."""
    out = {}
    for i in range(0, len(titles), 40):
        batch = titles[i:i + 40]
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "titles": "|".join(batch), "prop": "categories",
            "cllimit": "max", "redirects": 1, "format": "json"})
        q = _get(url)["query"]
        norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
        red = {x["from"]: x["to"] for x in q.get("redirects", [])}
        page = {p["title"]: ("missing" not in p,
                             " ".join(c["title"] for c in p.get("categories", [])))
                for p in q["pages"].values()}
        for t in batch:
            canon = red.get(norm.get(t, t), norm.get(t, t))
            exists, cats = page.get(canon, (False, ""))
            out[t] = (exists, canon, cats)
    return out


def _choose_titles(names):
    """name -> canonical Wikipedia title that is specifically this Pokémon."""
    dis = _resolve([f"{n} (Pokémon)" for n in names])
    bare = _resolve(names)
    chosen = {}
    for n in names:
        d_exists, d_canon, _ = dis[f"{n} (Pokémon)"]
        cand = d_canon if (d_exists and "List of" not in d_canon) else None
        if cand is None:
            b_exists, b_canon, b_cats = bare[n]
            if b_exists and "List of" not in b_canon and (
                    "Pokémon" in b_cats or "Pokemon" in b_cats):
                cand = b_canon
        if cand and cand.replace(" (Pokémon)", "").lower() == n.lower():
            chosen[n] = cand
    return chosen


def _annual_views(item):
    name, title = item
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"en.wikipedia/all-access/all-agents/"
           f"{urllib.parse.quote(title, safe='')}/monthly/{_PV_WINDOW[0]}/{_PV_WINDOW[1]}")
    try:
        return name, sum(it["views"] for it in _get(url).get("items", []))
    except Exception:
        return name, 0


def fetch(names) -> dict:
    """name -> 12-month en.wikipedia article views (only names with a match)."""
    chosen = _choose_titles(sorted(set(names)))
    views = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for name, v in ex.map(_annual_views, chosen.items()):
            if v > 0:
                views[name] = v
    return views


def main() -> None:
    cards = json.load(open(config.SITE_DATA / "cards.json", encoding="utf-8"))
    # Collapse Mega/form variants to the base character key.
    names = {list(popularity._variant_keys(c["base_name"]))[-1]
             for c in cards if c.get("supertype") == "Pokémon" and c.get("base_name")}
    views = fetch(names)
    payload = {"views": views,
               "window": f"{_PV_WINDOW[0]}..{_PV_WINDOW[1]}",
               "note": "en.wikipedia monthly article views, title-matched to the Pokémon"}
    json.dump(payload, open(_WIKI_OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {len(views)} Pokémon article view counts -> {_WIKI_OUT}")


if __name__ == "__main__":
    main()
