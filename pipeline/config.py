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

# Feature set fed to the price model. `live` = computable today from free data;
# `stub` = needs a paid/scraped feed (eBay/PSA/Trends) — implemented as a
# pluggable signal that returns a neutral value until its feed is wired.
FEATURES = {
    "char_premium":          {"label": "Character Premium",   "status": "live",  "min": 0, "max": 10},
    "scarcity":              {"label": "Scarcity Score",      "status": "live",  "min": 0, "max": 10},
    "pull_cost":             {"label": "Cost to pull ($)",          "status": "live", "min": 0, "max": 30000},
    "months_since_release":  {"label": "Months Since Release","status": "live",  "min": 0, "max": 60},
    "set_rank":              {"label": "In-Set Rarity Rank",  "status": "live",  "min": 0, "max": 1},
    "demand_pressure":       {"label": "Demand Pressure (%)", "status": "stub",  "min": 0, "max": 20},
    "grading_intensity":     {"label": "Grading Intensity",   "status": "stub",  "min": 0, "max": 10},
    "universal_appeal":      {"label": "Universal Appeal",    "status": "stub",  "min": 0, "max": 10},
}

# Market-dynamics windows (days) for demand pressure / supply saturation shift.
DYN_SHORT_WINDOW = 7
DYN_LONG_WINDOW = 30

# Leaderboards: drop sub-floor cards (penny cards produce huge, meaningless %
# swings) and rank by RAW dollar gap (expected - market), like the reference
# site ("the raw value difference between the market price and what we expect").
LEADERBOARD_MIN_PRICE = 2.0
LEADERBOARD_SIZE = 50
