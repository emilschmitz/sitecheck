import asyncio
import argparse
import json
import os

from openai import AsyncOpenAI

from config import A2ASettings
from mcp_server import process_locations_batch


async def extract_addresses_from_document(
    document_text: str, settings: A2ASettings
) -> list[str]:
    """
    Subagent functionality: Reads unstructured legal documents and extracts addresses.
    Returns a clean list of structured addresses.
    """
    openai_client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.openrouter_api_key.get_secret_value(),
    )

    prompt = (
        """You are a legal assistant subagent extracting data for a real estate due diligence pipeline.
Extract a clean list of all physical real estate/property addresses mentioned in the following legal document or unstructured text.
Return ONLY a valid JSON object with a single key 'addresses' containing a list of strings.

Raw text:
"""
        + document_text
    )

    print("Subagent: Reading document and extracting addresses using LLM...")
    try:
        response = await openai_client.chat.completions.create(
            model=settings.extraction_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        addresses = data.get("addresses", [])
        print(f"Subagent: Extracted {len(addresses)} addresses from the document.")
        return addresses
    except Exception as e:
        print(f"\n⚠️ Subagent failed to extract addresses: {e}")
        return []


async def main():
    parser = argparse.ArgumentParser(
        description="A2A Workflow: Subagent extracts data, MCP Server processes it."
    )
    parser.add_argument(
        "--doc", type=str, required=True, help="Path to the unstructured text document"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run MCP in dry-run mode (metadata only) to save costs",
    )
    args = parser.parse_args()

    if not os.path.exists(args.doc):
        print(f"Error: Document '{args.doc}' not found.")
        return

    # Load settings locally
    settings = A2ASettings()  # type: ignore

    with open(args.doc, "r", encoding="utf-8") as f:
        document_text = f.read()

    # Step 1: Subagent extracts clean data
    addresses = await extract_addresses_from_document(document_text, settings)

    if not addresses:
        print("Subagent could not find any addresses to process.")
        return

    print("Found the following structured addresses:")
    for i, addr in enumerate(addresses, 1):
        print(f"  {i}. {addr}")

    # Step 2: Handoff to the "External" MCP Tool
    print(
        "\nSubagent: Handing off structured payload to the Site Check Pipeline MCP..."
    )

    # We simulate an agent invoking an MCP tool by calling the function directly
    mcp_result = await process_locations_batch(addresses, dry_run=args.dry_run)

    print("\nSubagent: MCP processing complete. Result:")
    print("-" * 50)
    print(mcp_result)
    print("-" * 50)


if __name__ == "__main__":
    asyncio.run(main())
