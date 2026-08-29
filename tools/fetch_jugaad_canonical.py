from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import time

import pandas as pd
from jugaad_data.nse import index_name_list, index_raw, index_tri_raw

START = date(2021, 8, 30)
END = date.today()
MIN_ROWS = 250
OUT = Path("jugaad_output")

TARGETS = {
    "capital-goods": "NIFTY CAPITAL GOODS",
    "cement": "NIFTY CEMENT",
    "chemicals": "NIFTY CHEMICALS",
    "consumer-durables": "NIFTY CONSUMER DURABLES",
    "consumer-services": "NIFTY CONSUMER SERVICES",
    "media": "NIFTY MEDIA",
    "oil-gas": "NIFTY OIL & GAS",
    "power": "NIFTY POWER",
    "private-bank": "NIFTY PRIVATE BANK",
    "realty": "NIFTY REALTY",
    "telecom": "NIFTY TELECOMMUNICATIONS",
    "infrastructure-logistics": "NIFTY INDIA INFRASTRUCTURE & LOGISTICS",
    "railways": "NIFTY INDIA RAILWAYS PSU",
    "digital": "NIFTY INDIA DIGITAL",
    "tourism": "NIFTY INDIA TOURISM",
    "energy": "NIFTY ENERGY",
    "commodities": "NIFTY COMMODITIES",
    "capital-markets": "NIFTY CAPITAL MARKETS",
    "services": "NIFTY SERVICES SECTOR",
    "rural": "NIFTY INDIA RURAL",
    "mobility": "NIFTY EV & NEW AGE AUTOMOTIVE",
    "reit-invit": "NIFTY REITS & INVITS",
}


def as_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df.columns = [str(c).strip() for c in df.columns]
    date_col = next((c for c in df.columns if c.lower() in {"date", "historicaldate", "historical date"}), None)
    value_col = next((c for c in df.columns if c.lower() in {"close", "close index", "index value", "trindexvalue", "tr index value", "total return index value"}), None)
    if date_col is not None:
        df["date"] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    if value_col is not None:
        df["close"] = pd.to_numeric(df[value_col].astype(str).str.replace(",", "", regex=False), errors="coerce")
    if "date" in df and "close" in df:
        df = df[["date", "close"]].dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return df


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Jugaad-data version: 0.35.5", flush=True)
    print(f"Period: {START} -> {END}", flush=True)

    catalogue = index_name_list("Sectoral Indices", "Historical Index Data")
    thematic = index_name_list("Thematic Indices", "Historical Index Data")
    available = {str(x).strip().upper() for x in (catalogue + thematic)}
    print(f"Catalogue names discovered: {len(available)}", flush=True)

    results = []
    for exposure, index_name in TARGETS.items():
        print("=" * 78, flush=True)
        print(f"{exposure}: {index_name}", flush=True)
        if index_name.upper() not in available:
            print("CATALOGUE: NOT FOUND", flush=True)
            results.append((exposure, "not_in_catalogue", 0, 0))
            continue

        try:
            print("  fetching OHLC/index history...", flush=True)
            raw = index_raw(index_name, START, END)
            df = as_frame(raw)
            print(f"  index rows: {len(df)}", flush=True)

            print("  fetching TRI history...", flush=True)
            tri_raw = index_tri_raw(index_name, index_name, START, END)
            tri = as_frame(tri_raw)
            print(f"  TRI rows:   {len(tri)}", flush=True)

            if not tri.empty and len(tri) >= MIN_ROWS:
                tri.to_parquet(OUT / f"{exposure}.parquet", index=False, engine="pyarrow")
                print(f"  SAVED TRI: {OUT / f'{exposure}.parquet'}", flush=True)
                results.append((exposure, "tri", len(df), len(tri)))
            elif not df.empty and len(df) >= MIN_ROWS:
                df.to_parquet(OUT / f"{exposure}.parquet", index=False, engine="pyarrow")
                print(f"  SAVED PRICE: {OUT / f'{exposure}.parquet'}", flush=True)
                results.append((exposure, "price_only", len(df), len(tri)))
            else:
                results.append((exposure, "insufficient", len(df), len(tri)))
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}", flush=True)
            results.append((exposure, "error", 0, 0))
        time.sleep(1.0)

    summary = pd.DataFrame(results, columns=["exposure", "result", "index_rows", "tri_rows"])
    summary.to_csv(OUT / "summary.csv", index=False)
    print("=" * 78, flush=True)
    print(summary.to_string(index=False), flush=True)
    print(f"Saved output directory: {OUT.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
