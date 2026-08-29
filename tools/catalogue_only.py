from jugaad_data.nse import NSEIndex


def main():
    nse = NSEIndex()
    names = nse.get_index_list()
    print("=" * 80)
    print("JUGAAD-DATA — NSE INDEX CATALOGUE ONLY")
    print("=" * 80)
    print(f"Total catalogue entries: {len(names)}\n")
    for i, name in enumerate(names, 1):
        print(f"{i:02d}. {name}")
    print("\n" + "=" * 80)
    print(f"TOTAL: {len(names)}")
    print("NO HISTORICAL DATA REQUESTED")
    print("=" * 80)


if __name__ == "__main__":
    main()
