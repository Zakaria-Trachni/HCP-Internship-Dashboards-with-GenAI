"""Generate a generic sample sales dataset so the system can be demoed
without depending on any specific industry CSV.

The generated file deliberately mixes column types so the profiler has
something to do:
  - order_date           (datetime)
  - region, category, channel, customer_segment (low-card dimensions)
  - product_id           (identifier)
  - quantity, unit_price, discount_pct (measures)
  - revenue              (measure, derived)
  - is_returning_customer (boolean)
  - notes                (free text — will be classified as TEXT)
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


REGIONS = ["North", "South", "East", "West", "Central"]
CATEGORIES = ["Electronics", "Apparel", "Home & Kitchen", "Sports", "Books", "Toys"]
CHANNELS = ["Online", "Retail Store", "Partner", "Marketplace"]
SEGMENTS = ["Consumer", "SMB", "Enterprise"]
PRODUCT_IDS = [f"SKU-{1000 + i}" for i in range(120)]
NOTE_TEMPLATES = [
    "expedited shipping requested",
    "gift wrap",
    "bulk order",
    "first-time customer",
    "promo code applied",
    "",  # most rows have no note
    "", "", "", "",
]


def generate(rows: int = 4000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    random.seed(seed)

    start = date.today() - timedelta(days=540)
    order_dates = [start + timedelta(days=int(d)) for d in rng.integers(0, 540, rows)]

    regions = rng.choice(REGIONS, rows, p=[0.22, 0.20, 0.18, 0.22, 0.18])
    categories = rng.choice(CATEGORIES, rows, p=[0.28, 0.22, 0.18, 0.12, 0.10, 0.10])
    channels = rng.choice(CHANNELS, rows, p=[0.55, 0.20, 0.10, 0.15])
    segments = rng.choice(SEGMENTS, rows, p=[0.65, 0.25, 0.10])
    products = rng.choice(PRODUCT_IDS, rows)

    quantity = rng.integers(1, 12, rows)
    unit_price = np.round(rng.gamma(shape=2.5, scale=22, size=rows) + 5, 2)
    discount = np.round(rng.choice([0, 0, 0, 0.05, 0.10, 0.15, 0.20], rows), 2)
    revenue = np.round(quantity * unit_price * (1 - discount), 2)

    is_returning = rng.choice([True, False], rows, p=[0.4, 0.6])
    notes = [random.choice(NOTE_TEMPLATES) for _ in range(rows)]

    # Inject some realistic mess so the data prep agent has work to do.
    df = pd.DataFrame({
        "order_date": [d.isoformat() for d in order_dates],  # strings, not dt
        "region": regions,
        "category": categories,
        "channel": channels,
        "customer_segment": segments,
        "product_id": products,
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_pct": discount,
        "revenue": revenue,
        "is_returning_customer": is_returning,
        "notes": notes,
    })

    # Sprinkle missing values in a measure column.
    miss_idx = rng.choice(rows, size=rows // 50, replace=False)
    df.loc[miss_idx, "unit_price"] = np.nan

    # Add a few duplicate rows.
    dup_count = max(5, rows // 200)
    dups = df.sample(dup_count, random_state=seed)
    df = pd.concat([df, dups], ignore_index=True)

    # Whitespace pollution in a categorical.
    pollute_idx = rng.choice(len(df), size=len(df) // 80, replace=False)
    df.loc[pollute_idx, "region"] = df.loc[pollute_idx, "region"].astype(str) + " "

    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="./data/sample_sales.csv")
    p.add_argument("--rows", type=int, default=4000)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = generate(args.rows, args.seed)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df):,} rows × {df.shape[1]} cols -> {out}")


if __name__ == "__main__":
    main()
