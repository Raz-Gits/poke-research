"""Central configuration for the Price Lab pipeline.

Everything tunable lives here so the rest of the pipeline stays declarative.
Values marked ESTIMATE are rough secondary-market figures you should refine
(the model and EV math are only as good as these).
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
NORMALIZED = DATA / "normalized"
SNAPSHOTS = DATA / "snapshots"
SITE_DATA = ROOT / "docs" / "data"  # GitHub Pages serves /docs as the site root
for _p in (RAW, NORMALIZED, SNAPSHOTS, SITE_DATA):
    _p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Data source: pokemontcg.io (free; optional key raises rate limits)
# ---------------------------------------------------------------------------
API_BASE = "https://api.pokemontcg.io/v2"
API_KEY = os.environ.get("POKEMONTCG_API_KEY", "")  # optional

# When a card has several printings/variants, pick the market price in this
# order of preference (first one present wins).
VARIANT_PRIORITY = [
    "holofoil",
    "reverseHolofoil",
    "normal",
    "1stEditionHolofoil",
    "unlimitedHolofoil",
]

# ---------------------------------------------------------------------------
# Sets to track. Sealed EV is reported two ways so you can compare:
#   * single loose booster pack:  pack_price  (ev_per_pack vs this)
#   * Elite Trainer Box (ETB):    etb_price + packs_per_etb (ev_per_etb vs this)
# We use ETBs (not booster boxes) because every set ships a 9-pack standard ETB,
# while booster boxes don't exist for the special/Mega-era sets. All STANDARD
# (non-Pokémon-Center) ETBs = 9 packs; PC ETBs are 11.
#
# PRICES are TCGplayer-sourced mid-2026 estimates (TCGplayer is JS-rendered, so
# they can't be live-scraped — paste exact numbers here to lock them in). Two
# ETB prices flagged lower-confidence below.
# ---------------------------------------------------------------------------
# retail_pack_price = MSRP / sticker price of one pack — drives the per-card
# "cost to pull at retail". pack_price = current SECONDARY loose-pack price —
# drives single-pack rip EV (what a pack is worth vs what it costs on the market).
_ETB = 9  # packs in a standard Elite Trainer Box (SV era)
SETS = {
    "sv3pt5": {"name": "151",                  "pack_price": 12.0, "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 135.0},
    "sv8pt5": {"name": "Prismatic Evolutions", "pack_price": 18.0, "retail_pack_price": 4.99, "packs_per_etb": _ETB, "etb_price": 155.0},
    "sv8":    {"name": "Surging Sparks",       "pack_price": 7.0,  "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 120.0},
    "sv4pt5": {"name": "Paldean Fates",        "pack_price": 10.0, "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 110.0},  # etb low-confidence
    "sv6pt5": {"name": "Shrouded Fable",       "pack_price": 10.0, "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 110.0},  # etb low-confidence
    "sv7":    {"name": "Stellar Crown",        "pack_price": 6.0,  "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 130.0},
    "sv6":    {"name": "Twilight Masquerade",  "pack_price": 5.0,  "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 70.0},
    "sv5":    {"name": "Temporal Forces",      "pack_price": 6.0,  "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 130.0},
    "sv9":    {"name": "Journey Together",     "pack_price": 6.81,  "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 131.08},  # TCGplayer actual
    "sv10":   {"name": "Destined Rivals",      "pack_price": 10.62, "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 208.13},  # TCGplayer actual
    "zsv10pt5": {"name": "Black Bolt",         "pack_price": 13.58, "retail_pack_price": 4.49, "packs_per_etb": _ETB, "etb_price": 172.27},  # TCGplayer actual
    # Mega Evolution series (2025-2026)
    "me1":    {"name": "Mega Evolution",       "pack_price": 7.50,  "retail_pack_price": 4.99, "packs_per_etb": _ETB, "etb_price": 120.19},  # TCGplayer actual
    "me2pt5": {"name": "Ascended Heroes",      "pack_price": 13.58, "retail_pack_price": 4.99, "packs_per_etb": _ETB, "etb_price": 181.75},  # TCGplayer actual
    "me3":    {"name": "Perfect Order",        "pack_price": 6.0,  "retail_pack_price": 4.99, "packs_per_etb": _ETB, "etb_price": 90.0},
    "me4":    {"name": "Chaos Rising",         "pack_price": 6.0,  "retail_pack_price": 4.99, "packs_per_etb": _ETB, "etb_price": 92.0},
}

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
# His insight: one global regression won't fit thousands of cards — cluster
# first, then fit a model per cluster. We cluster on rarity tier (the cheapest
# robust clustering), with a per-set fallback when a cluster is too small.
MIN_CLUSTER_SIZE = 12          # below this, fall back to the global model
RIDGE_ALPHA = 1.0              # L2 regularization for the per-cluster ridge

# Feature set fed to the price model. LEAN 3-feature set, adopted 2026-06-21 after
# the multi-agent walk-forward backtest audit. We dropped:
#   * set_rank  — a within-cluster near-constant (std 0.01-0.10) collinear with
#                 scarcity (corr 0.87): redundant after clustering.
#   * pull_cost — extreme right-skew (max ~12.6k) that duplicates rarity once we
#                 cluster on supertype·rarity.
#   * the 3 dead stubs (demand_pressure / grading_intensity / universal_appeal) —
#                 std=0 so ridge zeroed them anyway, but they shipped 3 useless
#                 sliders AND were a silent look-ahead trap (a future non-neutral
#                 stub with leakage could slip into the model unnoticed).
# Measured lift on 123 weekly cuts: all-cards IC +0.094 -> +0.110, decile $-spread
# +18%, fresh-release IC held (~+0.26). set_rank/pull_cost are STILL computed
# (signals.py / build.py) for display + sealed-EV — they are just not model inputs.
# Re-add a feature ONLY when its feed has enough non-leaking history to backtest.
FEATURES = {
    "char_premium":          {"label": "Character Premium",   "status": "live",  "min": 0, "max": 10},
    "scarcity":              {"label": "Scarcity Score",      "status": "live",  "min": 0, "max": 10},
    "months_since_release":  {"label": "Months Since Release","status": "live",  "min": 0, "max": 60},
}

# Market-dynamics windows (days) for demand pressure / supply saturation shift.
DYN_SHORT_WINDOW = 7
DYN_LONG_WINDOW = 30

# Leaderboards: drop sub-floor cards (penny cards produce huge, meaningless %
# swings) and rank by RAW dollar gap (expected - market), like the reference
# site ("the raw value difference between the market price and what we expect").
LEADERBOARD_MIN_PRICE = 2.0
LEADERBOARD_SIZE = 50

# Leaderboard gating (2026-06-21 backtest audit). The model only has measured edge
# where the walk-forward IC is positive: fresh releases (+0.26) and the cheap/low-
# mid + marquee price tiers ($2-20 IC +0.09..+0.14, $100+ IC +0.03). The MATURE
# MID-PRICE zone [$20,$100) is significantly WRONG-signed (IC -0.05), so we do NOT
# surface over/under calls there. A card is SURFACED on the leaderboard if it's
# FRESH or its price is OUTSIDE the dead zone — keeping marquee chase cards in.
GATE_FRESH_AGE_DAYS = 35
GATE_DEAD_LO = 20.0     # \  cards in [GATE_DEAD_LO, GATE_DEAD_HI) that are NOT fresh
GATE_DEAD_HI = 100.0    # /  are the measured dead zone — suppressed from surfacing

# Chase-premium gate (2026-06-22). Within a supertype·rarity cluster the ridge
# reverts to the cluster center, so the priciest "grail" cards (e.g. Moonbreon) get
# flagged hugely "overvalued" purely because nothing in the 3 features explains their
# premium — the over-board becomes a price-sorted list of expensive cards. The
# backtest already shows ~0 edge on mature cards, so for a MATURE card whose market
# price exceeds this multiple of the model's estimate we DON'T surface an over/under
# call — we mark it "no edge — chase premium the model can't price."
CHASE_PREMIUM_MULT = 1.75  # market > 1.75x expected (mature) => unexplained chase premium

# Plain-language market-signal labels (pipeline/signal_labels.py). A RULES layer
# that fuses recent price move + demand/supply into one English verdict per card
# (e.g. "Heating up", "Opportunity — dipping with firm demand", "Cooling"). These
# are DESCRIPTIVE only — they never feed expected_price (demand stays out of the
# model until forward-validated). Thresholds calibrated 2026-06-21 against the live
# eBay feed: demand_pressure median ~1%, p90 ~18% -> HOT=15 catches the real tail;
# supply_saturation is flat 1.0 until >7d of span, so "cooling/loosening" clauses
# stay dark until the span grows, then light up on their own.
SIGNAL_PRICE_WINDOW_DAYS = 7   # look-back for the recent price move
SIGNAL_PRICE_UP_PCT = 3.0      # >= this over the window = "rising"
SIGNAL_PRICE_DOWN_PCT = -3.0   # <= this = "falling"
SIGNAL_DEMAND_HOT = 15.0       # demand_pressure (sell-through %) >= this = firm demand
SIGNAL_SAT_TIGHTEN = 0.97      # supply_saturation < this = supply contracting
SIGNAL_SAT_LOOSEN = 1.03       # supply_saturation > this = supply building

# Demand collector: sweep a FIXED, valuable-first universe of this size EVERY day
# (not the old budget-truncated variable slice). The SAME cards then get an active-
# listing count daily, so day-over-day demand diffs actually accrue. Price-ordered,
# so the SAME top cards are covered first every day and diffs accrue reliably.
# Widened 150 → 850 (2026-06-21) to cover the ENTIRE priced universe above the
# $2 leaderboard floor (~847 cards) every day — so every surfaced card gets a live
# demand/supply read, matching the reference site's coverage. 850 calls/day is far
# under the ~5k/day quota; the binding constraint was never the daily quota but
# eBay's PER-SECOND burst limit, which our 4 req/s pacing (REQUEST_PAUSE_S) already
# respects. At ~2s/card that's a ~28-min single run (SWEEP_TIME_BUDGET_S=1800s).
# Price-ordered, so if a run is throttled it drops only the CHEAPEST tail.
DEMAND_UNIVERSE_SIZE = 850
