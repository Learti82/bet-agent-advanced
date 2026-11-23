"""Research links for the manual workflow.

MatchEdge does not scrape statistics sites. It generates links you open yourself; you paste what
you find into the research panel together with the URL and the time you checked it.
Footiqo's URL scheme is not documented, so we link to its home page and to a site-restricted web
search rather than guessing page addresses.
"""
from __future__ import annotations

from urllib.parse import quote_plus

OFFICIAL = {
    "ENG_1": ("Premier League", "https://www.premierleague.com/fixtures"),
    "ENG_2": ("EFL", "https://www.efl.com/fixtures/"), "ENG_3": ("EFL", "https://www.efl.com/fixtures/"),
    "ENG_4": ("EFL", "https://www.efl.com/fixtures/"),
    "ESP_1": ("LaLiga", "https://www.laliga.com/en-GB/laliga-easports/calendar"),
    "GER_1": ("Bundesliga", "https://www.bundesliga.com/en/bundesliga/matchday"),
    "GER_2": ("2. Bundesliga", "https://www.bundesliga.com/en/2bundesliga/matchday"),
    "ITA_1": ("Lega Serie A", "https://www.legaseriea.it/en/serie-a/calendar"),
    "FRA_1": ("Ligue 1", "https://ligue1.com/en/fixtures"),
    "NED_1": ("Eredivisie", "https://eredivisie.eu/competition/fixtures/"),
    "POR_1": ("Liga Portugal", "https://www.ligaportugal.pt/en/liga/calendario/"),
    "SCO_1": ("SPFL", "https://spfl.co.uk/fixtures"),
    "BEL_1": ("Pro League", "https://www.proleague.be/"),
    "TUR_1": ("TFF", "https://www.tff.org/"),
    "USA_1": ("MLS", "https://www.mlssoccer.com/schedule/"),
    "UEFA_1_champions-league": ("UEFA Champions League", "https://www.uefa.com/uefachampionsleague/fixtures-results/"),
    "UEFA_1_europa-league": ("UEFA Europa League", "https://www.uefa.com/uefaeuropaleague/fixtures-results/"),
    "UEFA_1_conference-league": ("UEFA Conference League", "https://www.uefa.com/uefaconferenceleague/fixtures-results/"),
}


def research_links(fixture: dict) -> list[dict]:
    home, away = fixture["home"], fixture["away"]
    code = fixture["competition"]
    q = quote_plus(f"{home} {away}")
    links = [
        {"name": "Footiqo (home page)", "url": "https://footiqo.com/", "kind": "statistics",
         "note": "Open, find the match, and paste relevant statistics into the research panel."},
        {"name": "Footiqo (site search)", "url": f"https://duckduckgo.com/?q=site%3Afootiqo.com+{q}",
         "kind": "statistics", "note": "Web search restricted to footiqo.com."},
        {"name": "Team news search", "url": f"https://duckduckgo.com/?q={q}+team+news+injuries+lineup",
         "kind": "team news", "note": "Lineups and injuries are not in the dataset."},
        {"name": "Open-Matchday source data",
         "url": f"https://github.com/oladeeayo/open-matchday/tree/master/data/{code}", "kind": "dataset",
         "note": "The CSV files this analysis is based on."},
    ]
    off = OFFICIAL.get(code) or OFFICIAL.get("_".join(code.split("_")[:2]))
    if off:
        links.insert(0, {"name": f"Official: {off[0]}", "url": off[1], "kind": "official",
                         "note": "Verify date, kickoff time and status here."})
    else:
        links.insert(0, {"name": "Official fixture (search)",
                         "url": f"https://duckduckgo.com/?q={quote_plus(fixture['competition_name'])}+official+fixtures+{q}",
                         "kind": "official", "note": "Find the competition's official site to verify the fixture."})
    return links
