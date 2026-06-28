from bs4 import BeautifulSoup
from collections import defaultdict
from src.config.settings import MCINFO_URL
from src.hkha.player_parser import parse_player_row


def _extract_team_block(container):
    """Extract either Home or Away block"""
    header = container.find("div", class_=["Home", "Away"])
    team_name = header.find_all("span")[0].text.strip()
    score = header.find("span", style=True).find("span").text.strip()

    players = []

    for div in container.find_all("div", class_="team"):
        raw = div.get_text(" ", strip=True)
        if not raw or raw.startswith("Score"):
            continue

        player = parse_player_row(raw)

        # Goals
        score_div = div.find_all("div")
        for d in score_div:
            if "Score:" in d.get_text():
                try:
                    player["Goals Scored"] = int(d.get_text().split(":")[1].strip())
                except:
                    player["Goals Scored"] = 0

        # Player team (play-up)
        pt = div.find("b", class_="playerteam")
        if pt:
            player["Player Team"] = pt.text.strip()
        else:
            player["Player Team"] = team_name

        player["Team"] = team_name

        players.append(player)

    return {
        "team": team_name,
        "score": score,
        "players": players
    }


def get_match_card(session, fixture_id):
    response = session.get(
        MCINFO_URL,
        params={"FixtureId": fixture_id},
        timeout=30
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    containers = soup.find_all("div", style=lambda v: v and "width: 480px" in v)

    match_data = {
        "fixture_id": fixture_id,
        "teams": []
    }

    for c in containers:
        match_data["teams"].append(_extract_team_block(c))

    # flatten for airtable
    flat_players = []
    for t in match_data["teams"]:
        flat_players.extend(t["players"])

    return {
        "fixture_id": fixture_id,
        "players": flat_players
    }
    
