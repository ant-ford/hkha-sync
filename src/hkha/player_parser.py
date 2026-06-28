import re

CARD_PATTERN = re.compile(r'(Y[1-7]|R[1-7])')


def parse_player_row(raw_text: str):
    text = ' '.join(raw_text.split())

    captain = '*' in text
    goalkeeper = '#' in text
    u21 = 'U21' in text
    vp = ' VP ' in f' {text} '

    cards = CARD_PATTERN.findall(text)

    cleaned = text.replace('*', '').replace('#', '')
    cleaned = cleaned.replace('U21', '').replace('VP', '').strip()

    return {
        'RawPlayerName': text,
        'CleanName': cleaned,
        'Captain': captain,
        'Goalkeeper': goalkeeper,
        'U21': u21,
        'VP': vp,
        'Cards': ','.join(cards)
    }
