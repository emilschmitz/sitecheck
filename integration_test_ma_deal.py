import asyncio
import argparse
import os
import pandas as pd
from mcp_server.server import process_locations_batch


async def run_ma_due_diligence_test(
    filepath: str, dry_run: bool = True, max_locations: int | None = None
):
    print("=" * 70)
    print("MOCK M&A DEAL: Amazon is acquiring Target")
    print("Legal Due Diligence: Verifying 2,000 store locations in the contract.")
    print("=" * 70)

    addresses = []

    if os.path.exists(filepath):
        print(f"Loading dataset from {filepath}...")
        df = pd.read_csv(filepath, encoding="latin1")

        address_col = next(
            (
                col
                for col in df.columns
                if "address" in col.lower() and "ip" not in col.lower()
            ),
            None,
        )
        city_col = next((col for col in df.columns if "city" in col.lower()), None)
        state_col = next(
            (
                col
                for col in df.columns
                if "state" in col.lower() or "province" in col.lower()
            ),
            None,
        )

        if not address_col:
            print(
                "Warning: Could not automatically detect an 'address' column. Trying default index."
            )
            address_col = df.columns[0]

        for _, row in df.iterrows():
            addr_parts = [str(row[address_col])]
            if city_col and not pd.isna(row[city_col]):
                addr_parts.append(str(row[city_col]))
            if state_col and not pd.isna(row[state_col]):
                addr_parts.append(str(row[state_col]))

            addresses.append(", ".join(addr_parts))
    else:
        print(f"Dataset '{filepath}' not found.")
        print("Using a small mock sample of Target locations...")
        addresses = [
            "100 N 8th St, Minneapolis, MN 55403",
            "1901 E Madison St, Seattle, WA 98122",
            "115 West Colorado Boulevard, Pasadena, CA 91105",
            "401 Biscayne Blvd, Miami, FL 33132",
            "225 Bush St, San Francisco, CA 94104",
        ]

    if max_locations and len(addresses) > max_locations:
        print(f"Testing Limit Reached: Processing the first {max_locations} locations.")
        addresses = addresses[:max_locations]

    print(f"\nContract Exhibit A lists {len(addresses)} Target properties to verify.")

    print("\nInitiating Automated Real Estate Due Diligence Pipeline...")
    val_status = (
        "ON (Metadata check only)"
        if dry_run
        else "OFF (Full LLM Vision analysis active)"
    )
    print(f"Dry Run Mode: {val_status}\n")

    result = await process_locations_batch(
        addresses=addresses,
        analysis_prompt="Analyze this Target store for general condition and brand visibility.",
        analysis_schema='{"condition": "string", "brand_visible": "boolean"}',
        dry_run=dry_run
    )

    print("\n" + "=" * 70)
    print("DUE DILIGENCE PIPELINE COMPLETED")
    print("=" * 70)
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Mock M&A Deal - Amazon/Target Integration Test"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/target_locations.csv",
        help="Path to the dataset",
    )
    parser.add_argument(
        "--live", action="store_true", help="Run with live vision analysis"
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Max locations to process"
    )

    args = parser.parse_args()
    asyncio.run(
        run_ma_due_diligence_test(
            args.dataset, dry_run=not args.live, max_locations=args.limit
        )
    )
