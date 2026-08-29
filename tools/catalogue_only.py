from __future__ import annotations

from jugaad_data.nse import index_name_list


def main() -> None:
    # Same Jugaad-data API already proven by the canonical-history workflow.
    # This retrieves catalogue names only; it does not request price history.
    sectoral = index_name_list("Sectoral Indices", "Historical Index Data")
    thematic = index_name_list("Thematic Indices", "Historical Index Data")

    names = list(dict.fromkeys(
        [str(x).strip() for x in (sectoral + thematic) if str(x).strip()]
    ))

    print("=" * 80, flush=True)
    print("JUGAAD-DATA — NSE INDEX CATALOGUE ONLY", flush=True)
    print("=" * 80, flush=True)
    print(f"Sectoral entries: {len(sectoral)}", flush=True)
    print(f"Thematic entries: {len(thematic)}", flush=True)
    print(f"Unique catalogue entries: {len(names)}\n", flush=True)

    for i, name in enumerate(names, 1):
        print(f"{i:02d}. {name}", flush=True)

    print("\n" + "=" * 80, flush=True)
    print(f"TOTAL UNIQUE: {len(names)}", flush=True)
    print("NO HISTORICAL DATA REQUESTED", flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
