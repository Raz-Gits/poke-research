"""Cross-generation character popularity prior.

SOURCE: the official **2020 "Pokemon of the Year" global poll** (Pokemon Day
2020 — a worldwide fan vote whose results were announced Feb 27, 2020). The
published per-region Top-30 tables (each with global vote counts) merged and
re-sorted by vote count yield a verified overall ranking 240 deep; ranks 1-30
here exactly match Bulbapedia's published overall Top 30. Vote counts beyond
rank 240 were never released publicly.

  Bulbapedia: https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_of_the_Year

WHY: this is a price-INDEPENDENT popularity ground truth covering Gen 1-8. It
anchors the character-premium feature so *genuine fame* drives the score instead
of in-set chase frequency (which only sees our handful of Scarlet & Violet sets
and inflates whichever modern Legendaries happen to have pricey chase cards).

HOW the 0-10 score is built (RANK-based, deliberately top-compressed):
  Card-value popularity is a *tier*, not a fine gradient — a Mew or Mewtwo sells
  broadly even if a favorites poll ranks niche picks above them. So we don't map
  votes linearly; instead we map poll RANK through a two-segment curve with a
  high plateau and a tunable cutoff:
    * Ranks 1..ELITE_RANK (the "premium tier") map from POLL_TOP (9.9) down to
      only ELITE_BOTTOM (9.4) — so every well-known Pokemon lands ~9.4-9.9 with
      just minor separation at the top.
    * Ranks ELITE_RANK..240 taper from ELITE_BOTTOM down to POLL_FLOOR (7.5) —
      this is where the real drop-off lives. Move ELITE_RANK / the floors to
      slide the cutoff.
  * USER_OVERRIDES win over the poll (hand-pinned anchors). 10.0 is reserved for
    them so the user's named icons (Charizard/Pikachu/Gengar) sit at the very top.
  * Characters NOT in the poll (all Gen 9 newcomers, plus poll ranks 241+) get
    no prior here -> signals.py falls back to the structural signal, compressed
    BELOW POLL_FLOOR so any poll-ranked classic outranks any unranked newcomer.

Mega / regional / form variants inherit the base Pokemon's score
("Mega Charizard Y" -> Charizard).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Hand-pinned anchors — these WIN over the poll. 10.0 is reserved for them.
# (Set by the user: the marquee chase characters that command a card premium
# regardless of where a favorites poll ranks them — e.g. Pikachu is only poll
# rank 19 but is a perennial card-value driver.)
# ---------------------------------------------------------------------------
USER_OVERRIDES: Dict[str, float] = {
    "Charizard": 10.0,
    "Pikachu": 10.0,
    "Gengar": 10.0,
    # Umbreon is no longer hard-pinned: at poll rank 5 the top-compressed curve
    # places it ~9.85 anyway, and pinning 9.5 would wrongly sink it below
    # less-popular Pokemon (Eevee, Sylveon). Re-add a line here to force a value.
}

# ---------------------------------------------------------------------------
# 2020 Pokemon of the Year — name -> global vote count (overall rank in comment).
# ---------------------------------------------------------------------------
POLL_VOTES: Dict[str, int] = {
    "Greninja": 140559,    # 1
    "Lucario": 102259,     # 2
    "Mimikyu": 99077,      # 3
    "Charizard": 93968,    # 4
    "Umbreon": 67062,      # 5
    "Sylveon": 66029,      # 6
    "Garchomp": 61877,     # 7
    "Rayquaza": 60939,     # 8
    "Gardevoir": 60596,    # 9
    "Gengar": 60214,       # 10
    "Dragapult": 57973,    # 11
    "Tyranitar": 56834,    # 12
    "Bulbasaur": 56015,    # 13
    "Toxtricity": 55032,   # 14
    "Lugia": 53268,        # 15
    "Rowlet": 52367,       # 16
    "Aegislash": 51517,    # 17
    "Chandelure": 50943,   # 18
    "Pikachu": 48060,      # 19
    "Eevee": 47762,        # 20
    "Luxray": 46032,       # 21
    "Decidueye": 44011,    # 22
    "Zoroark": 43782,      # 23
    "Lycanroc": 42792,     # 24
    "Corviknight": 41711,  # 25
    "Flygon": 41420,       # 26
    "Hydreigon": 40054,    # 27
    "Sceptile": 38724,     # 28
    "Blaziken": 38307,     # 29
    "Snom": 38034,         # 30
    "Mudkip": 36920,       # 31
    "Dragonite": 36873,    # 32
    "Mew": 36266,          # 33
    "Metagross": 35631,    # 34
    "Typhlosion": 35184,   # 35
    "Noivern": 34795,      # 36
    "Scizor": 34691,       # 37
    "Piplup": 34680,       # 38
    "Mewtwo": 34585,       # 39
    "Infernape": 33267,    # 40
    "Ampharos": 32009,     # 41
    "Zeraora": 31691,      # 42
    "Alcremie": 30612,     # 43
    "Darkrai": 30544,      # 44
    "Goodra": 30209,       # 45
    "Espeon": 30052,       # 46
    "Incineroar": 29925,   # 47
    "Arcanine": 29795,     # 48
    "Jirachi": 29611,      # 49
    "Cyndaquil": 28332,    # 50
    "Milotic": 28295,      # 51
    "Absol": 27781,        # 52
    "Golisopod": 26975,    # 53
    "Cinderace": 26892,    # 54
    "Swampert": 26540,     # 55
    "Suicune": 26227,      # 56
    "Glaceon": 26161,      # 57
    "Zacian": 26158,       # 58
    "Primarina": 25953,    # 59
    "Yamper": 25695,       # 60
    "Salamence": 24920,    # 61
    "Arceus": 24502,       # 62
    "Aron": 24389,         # 63
    "Volcarona": 24389,    # 64
    "Lapras": 23411,       # 65
    "Haxorus": 22937,      # 66
    "Totodile": 22526,     # 67
    "Talonflame": 22328,   # 68
    "Serperior": 22269,    # 69
    "Oshawott": 21990,     # 70
    "Empoleon": 21773,     # 71
    "Dedenne": 21691,      # 72
    "Crobat": 21548,       # 73
    "Zekrom": 21477,       # 74
    "Furret": 21447,       # 75
    "Giratina": 21366,     # 76
    "Wooloo": 21266,       # 77
    "Victini": 20957,      # 78
    "Leafeon": 20859,      # 79
    "Yveltal": 20852,      # 80
    "Inteleon": 20697,     # 81
    "Torterra": 20632,     # 82
    "Celebi": 20492,       # 83
    "Goomy": 20299,        # 84
    "Sirfetch'd": 20217,   # 85
    "Reshiram": 20123,     # 86
    "Scorbunny": 20058,    # 87
    "Snorlax": 19768,      # 88
    "Krookodile": 19628,   # 89
    "Ninetales": 19044,    # 90
    "Tyrantrum": 18778,    # 91
    "Hatterene": 18581,    # 92
    "Chikorita": 18521,    # 93
    "Squirtle": 18476,     # 94
    "Ho-Oh": 18278,        # 95
    "Feraligatr": 18245,   # 96
    "Aggron": 18120,       # 97
    "Whimsicott": 17855,   # 98
    "Latias": 17478,       # 99
    "Shaymin": 17465,      # 100
    "Xerneas": 17415,      # 101
    "Bewear": 17181,       # 102
    "Sobble": 17155,       # 103
    "Snivy": 17020,        # 104
    "Altaria": 16814,      # 105
    "Blastoise": 16795,    # 106
    "Heracross": 16577,    # 107
    "Solgaleo": 16274,     # 108
    "Meltan": 16077,       # 109
    "Falinks": 16009,      # 110
    "Appletun": 15989,     # 111
    "Natu": 15699,         # 112
    "Eternatus": 15699,    # 113
    "Pichu": 15695,        # 114
    "Kyogre": 15585,       # 115
    "Mawile": 15523,       # 116
    "Zorua": 14910,        # 117
    "Vaporeon": 14887,     # 118
    "Buzzwole": 14747,     # 119
    "Houndoom": 14742,     # 120
    "Hawlucha": 14607,     # 121
    "Scolipede": 14536,    # 122
    "Muk": 14358,          # 123
    "Pyukumuku": 14358,    # 124
    "Dialga": 14292,       # 125
    "Togepi": 14288,       # 126
    "Gallade": 14144,      # 127
    "Reuniclus": 14129,    # 128
    "Staraptor": 14054,    # 129
    "Charmander": 14049,   # 130
    "Litten": 14005,       # 131
    "Morpeko": 13945,      # 132
    "Meloetta": 13915,     # 133
    "Silvally": 13897,     # 134
    "Ditto": 13843,        # 135
    "Meowstic": 13661,     # 136
    "Fennekin": 13508,     # 137
    "Grookey": 13478,      # 138
    "Togekiss": 13426,     # 139
    "Vikavolt": 13375,     # 140
    "Quagsire": 13308,     # 141
    "Grimmsnarl": 12923,   # 142
    "Salazzle": 12863,     # 143
    "Breloom": 12801,      # 144
    "Kommo-o": 12790,      # 145
    "Gliscor": 12676,      # 146
    "Zamazenta": 12641,    # 147
    "Torchic": 12568,      # 148
    "Latios": 12487,       # 149
    "Slowpoke": 12369,     # 150
    "Melmetal": 12356,     # 151
    "Marshadow": 12107,    # 152
    "Groudon": 11982,      # 153
    "Zygarde": 11943,      # 154
    "Centiskorch": 11619,  # 155
    "Nidoking": 11586,     # 156
    "Samurott": 11444,     # 157
    "Dracovish": 11436,    # 158
    "Lopunny": 11411,      # 159
    "Excadrill": 11376,    # 160
    "Porygon": 11311,      # 161
    "Lilligant": 11292,    # 162
    "Vulpix": 11224,       # 163
    "Psyduck": 11212,      # 164
    "Raichu": 11196,       # 165
    "Pinsir": 11162,       # 166
    "Litwick": 11140,      # 167
    "Jolteon": 11064,      # 168
    "Dragonair": 11051,    # 169
    "Frosmoth": 10988,     # 170
    "Rockruff": 10986,     # 171
    "Bisharp": 10975,      # 172
    "Bidoof": 10924,       # 173
    "Diancie": 10918,      # 174
    "Tsareena": 10900,     # 175
    "Delphox": 10889,      # 176
    "Turtwig": 10865,      # 177
    "Weavile": 10854,      # 178
    "Deoxys": 10842,       # 179
    "Braixen": 10807,      # 180
    "Grovyle": 10746,      # 181
    "Banette": 10579,      # 182
    "Venusaur": 10454,     # 183
    "Articuno": 10450,     # 184
    "Froslass": 10408,     # 185
    "Entei": 10404,        # 186
    "Espurr": 10402,       # 187
    "Eiscue": 10392,       # 188
    "Kyurem": 10338,       # 189
    "Hoopa": 10327,        # 190
    "Aurorus": 10321,      # 191
    "Pancham": 10187,      # 192
    "Quilava": 10032,      # 193
    "Magnemite": 9955,     # 194
    "Porygon2": 9902,      # 195
    "Cinccino": 9892,      # 196
    "Lunala": 9887,        # 197
    "Dragalge": 9882,      # 198
    "Emolga": 9798,        # 199
    "Pachirisu": 9694,     # 200
    "Rotom": 9417,         # 201
    "Treecko": 9339,       # 202
    "Wooper": 9323,        # 203
    "Pumpkaboo": 9162,     # 204
    "Roserade": 9092,      # 205
    "Trevenant": 9019,     # 206
    "Sableye": 9012,       # 207
    "Keldeo": 8915,        # 208
    "Lurantis": 8889,      # 209
    "Pangoro": 8859,       # 210
    "Mismagius": 8833,     # 211
    "Joltik": 8796,        # 212
    "Minccino": 8739,      # 213
    "Ludicolo": 8708,      # 214
    "Obstagoon": 8705,     # 215
    "Rillaboom": 8625,     # 216
    "Togedemaru": 8531,    # 217
    "Cramorant": 8436,     # 218
    "Shinx": 8373,         # 219
    "Phantump": 8231,      # 220
    "Toxapex": 8221,       # 221
    "Misdreavus": 8156,    # 222
    "Shuckle": 8129,       # 223
    "Tapu Koko": 8090,     # 224
    "Golurk": 8035,        # 225
    "Genesect": 7905,      # 226
    "Mudsdale": 7787,      # 227
    "Wobbuffet": 7745,     # 228
    "Necrozma": 7739,      # 229
    "Popplio": 7542,       # 230
    "Cosmog": 7515,        # 231
    "Kingdra": 7418,       # 232
    "Munchlax": 7289,      # 233
    "Ribombee": 7126,      # 234
    "Porygon-Z": 7040,     # 235
    "Shedinja": 6703,      # 236
    "Malamar": 6503,       # 237
    "Mightyena": 6459,     # 238
    "Heliolisk": 6386,     # 239
    "Froakie": 6293,       # 240
}

# ---------------------------------------------------------------------------
# Rank -> 0-10 score mapping. TOP-COMPRESSED on purpose: the famous Pokemon all
# cluster high (minor separation), and the real drop-off happens at a tunable
# cutoff. THESE FOUR KNOBS are the dials to slide — raise ELITE_RANK to widen the
# premium tier, raise POLL_FLOOR to lift everyone, etc.
# ---------------------------------------------------------------------------
POLL_TOP = 9.9      # rank-1 score (10.0 reserved for USER_OVERRIDES)
ELITE_RANK = 50     # ranks 1..ELITE_RANK are the "premium tier" (cluster high)
ELITE_BOTTOM = 9.4  # score at rank ELITE_RANK — premium tier spans [9.4, 9.9]
POLL_FLOOR = 7.5    # score at the last poll rank (240); unranked stay below this

# Poll rank by name (insertion order == rank order, 1-based).
_RANK = {name: i + 1 for i, name in enumerate(POLL_VOTES)}
_LAST_RANK = len(POLL_VOTES)


def _poll_score(rank: int) -> float:
    """Two-segment rank curve: a high plateau then a taper to POLL_FLOOR."""
    if rank <= ELITE_RANK:
        frac = (rank - 1) / (ELITE_RANK - 1)
        return POLL_TOP - frac * (POLL_TOP - ELITE_BOTTOM)
    frac = (rank - ELITE_RANK) / (_LAST_RANK - ELITE_RANK)
    return ELITE_BOTTOM - frac * (ELITE_BOTTOM - POLL_FLOOR)


# Precomputed name -> score for the poll.
POLL_SCORE: Dict[str, float] = {
    name: round(_poll_score(_RANK[name]), 4) for name in POLL_VOTES
}


def _variant_keys(base_name: str):
    """Yield lookup keys for a character, narrowing Mega/form variants to their
    base: 'Mega Charizard Y' -> 'Charizard X/Y/Z stripped' -> 'Charizard'."""
    yield base_name
    stem = base_name[5:] if base_name.startswith("Mega ") else base_name
    if stem != base_name:
        yield stem
    parts = stem.split()
    if len(parts) >= 2 and parts[-1] in {"X", "Y", "Z"}:
        yield " ".join(parts[:-1])


def popularity_prior(base_name: str) -> Tuple[Optional[float], Optional[str]]:
    """Return (score, source) for a character, or (None, None) if not anchored.

    source is 'user' (hand-pinned override, wins) or 'poll' (2020 poll). Mega/
    form variants inherit the base Pokemon. Characters with no prior return
    (None, None) so the caller can fall back to the structural signal.
    """
    if not base_name:
        return None, None
    keys = list(_variant_keys(base_name))
    for k in keys:
        if k in USER_OVERRIDES:
            return USER_OVERRIDES[k], "user"
    for k in keys:
        if k in POLL_SCORE:
            return POLL_SCORE[k], "poll"
    return None, None
