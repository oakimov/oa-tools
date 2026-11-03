#!/usr/bin/env python3
"""Rebill a Cursor usage export on the current plans.

Usage: python cursor_rebill.py usage-events.csv

Rates and plan terms were read on 2026-11-03. See README.md for the method.
"""
import sys
import pandas as pd

# USD per 1M tokens: input, cache write, cache read, output.
# Order matters: the first prefix that matches wins, so keep specific names first.
# Rates change, so check them against Cursor's models and pricing page.
RATES = {
    "grok-4.7-high-fast": (4, 4, 1, 12), "grok-4.7-low-fast": (4, 4, 1, 12),
    "grok": (2, 2, .5, 6), "cursor-grok-4.5": (4, 4, 1, 18), "cursor-grok": (2, 2, .5, 6),
    "composer-2.5-fast": (3, 3, .5, 15), "composer": (.5, .5, .2, 2.5),
    "claude-opus-5-5": (4, 5, .2, 20), "claude-sonnet-5-5": (2, 2.5, .1, 10),
    "claude-haiku-5-5": (.1, .125, .01, .5), "claude-4.6-sonnet": (3, 3.75, .3, 15),
    "claude-4.5-sonnet": (3, 3.75, .3, 15), "claude-4.5-haiku": (1, 1.25, .1, 5),
    "gemini-4-argon": (2, 2, .1, 10), "gemini-3.1": (2, 2, .2, 12),
    "gemini-3.8": (.75, .75, .075, 3.75), "glm-5p3-flash": (.15, .15, .029, .5),
    "glm-5p3": (1.4, 1.4, .26, 4.4), "kimi-k3": (3, 3, .3, 15),
    "muse-spark": (1.25, 1.25, .15, 4.25),
}  # GPT is left out on purpose, as OpenAI is leaving Cursor. Add it to compare.
LOW, HIGH = RATES["composer"], RATES["grok"]  # bracket for Auto and Grok Bot
PLANS = {"Ultra": (200, 1), "Super": (100, .3), "Premium": (30, .08)}
COLS = ["Input (w/o Cache Write)", "Input (w/ Cache Write)", "Cache Read", "Output Tokens"]

if len(sys.argv) != 2:
    sys.exit(__doc__)

df = pd.read_csv(sys.argv[1]).fillna({c: 0 for c in COLS})
df = df[df["Cost"] != "Free"]
df["day"] = pd.to_datetime(df["Date"]).dt.date

def cost(row, rate):
    return sum(row[c] * r for c, r in zip(COLS, rate)) / 1e6

def price(row):
    m = row["Model"]
    if m == "auto" or m.startswith("grok-bot"):
        return "unrated", cost(row, LOW), cost(row, HIGH)
    for name, rate in RATES.items():
        if m.startswith(name):
            pool = "cursor" if name.startswith(("grok", "cursor-grok", "composer")) else "third"
            return pool, cost(row, rate), cost(row, rate)
    return "unknown", 0, 0

df[["pool", "low", "high"]] = df.apply(price, axis=1, result_type="expand")
print(df.groupby("pool")[["low", "high"]].sum().round(2))
print("Not priced:", sorted(df[df["pool"] == "unknown"]["Model"].unique()))

third = df[df["pool"] == "third"]["low"].sum()
days = pd.date_range(df["day"].min(), df["day"].max()).date
daily = (df[df["pool"].isin(["cursor", "unrated"])].groupby("day")["low"].sum()
         .reindex(days, fill_value=0))

def overflow(pool):  # average across all seven possible reset days
    total = 0
    for reset in range(7):
        week = 0
        for i, usd in enumerate(daily):
            if i % 7 == reset and i > 0:
                total += max(0, week - pool)
                week = 0
            week += usd
        total += max(0, week - pool)
    return total / 7

floor = 2 * daily.sum() / (len(days) / 7)  # assumed Ultra pool, list value a week
print(f"Peak 7 days ${daily.rolling(7).sum().max():,.0f}, floor ${floor:,.0f} a week")
for plan, (fee, share) in PLANS.items():
    print(plan, f"minimum ${fee + third:,.0f},",
          f"with overflow ${fee + third + overflow(floor * share):,.0f}")
