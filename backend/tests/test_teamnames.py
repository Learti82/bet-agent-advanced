from matchedge.teamnames import TeamResolver, team_key


def test_team_key_normalisation():
    assert team_key("Stade Rennais FC") == team_key("Stade Rennais") == "stade rennais"
    assert team_key("Bodø/Glimt") == team_key("Bodo/Glimt") == "bodo glimt"
    assert team_key("Nordsjælland") == "nordsjaelland"
    assert team_key("FC Bayern München") == team_key("Bayern München") == "bayern munchen"
    assert team_key("1. FSV Mainz 05") == "mainz"
    assert team_key("VfB Stuttgart II") == "stuttgart ii"  # reserves stay distinct
    assert team_key("Dundee") != team_key("Dundee United")


def test_ambiguous_names_are_not_guessed():
    domestic = {"paris": {"FRA:paris"}, "paris saint germain": {"FRA:paris saint germain"},
                "barcelona": {"ESP:barcelona", "ECU:barcelona"}}
    r = TeamResolver(domestic, aliases={})
    assert r.resolve("UEFA_1_champions-league", "Barcelona") == "UEFA:barcelona"
    assert r.links["Barcelona"]["method"] == "ambiguous"


def test_alias_and_exact_links():
    domestic = {"paris saint germain": {"FRA:paris saint germain"}, "arsenal": {"ENG:arsenal"}}
    r = TeamResolver(domestic, aliases={"paris": "FRA:paris saint germain"})
    assert r.resolve("UEFA_1_champions-league", "Paris") == "FRA:paris saint germain"
    assert r.resolve("UEFA_1_champions-league", "Arsenal") == "ENG:arsenal"
    assert r.resolve("ENG_1_premier-league", "Arsenal") == "ENG:arsenal"
    # alias to a team that does not exist is ignored
    r2 = TeamResolver(domestic, aliases={"inter": "ITA:internazionale"})
    assert r2.resolve("UEFA_1_champions-league", "Inter") == "UEFA:inter"
