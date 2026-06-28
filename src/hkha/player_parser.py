import re

CARD_PATTERN = re.compile(r'(Y[1-7]|R[1-7])')


def parse_player_row(raw_text: str):
    text = " ".join(raw_text.split())

    captain = text.startswith("*")
    goalkeeper = text.startswith("#")
    u21 = "(u21)" in text.lower()
    vp = "(vp)" in text.lower()

    cards = CARD_PATTERN.findall(text)

    cleaned = text.replace("*", "").replace("#", "")
    cleaned = cleaned.replace("(U21)", "").replace("(vp)", "").strip()

    parts = cleaned.split("-", 1)
    jersey = None
    name = cleaned

    if len(parts) == 2:
        try:
            jersey = int(parts[0].strip())
            name = parts[1].strip()
        except:
            pass

    return {
        "RawPlayerName": name,
        "Jersey Number": jersey,
        "Captain": captain,
        "Goalkeeper": goalkeeper,
        "U21": u21,
        "VP": vp,
        "Cards": ",".join(cards),
        "Goals Scored": 0
    }
