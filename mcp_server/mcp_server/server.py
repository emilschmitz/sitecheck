import asyncio
import json
import os
import logging
from datetime import datetime
from typing import Any
from importlib.metadata import version

import aiohttp
import openpyxl
import pandas as pd
from fastmcp import FastMCP
from openpyxl.styles import PatternFill
from tqdm.asyncio import tqdm
from fastmcp import Context
from mcp_server.utils import check_street_view_metadata, get_google_maps_link, get_street_view_link, get_cardinal_direction
from mcp_server.vision import fetch_street_view_image, analyze_image_with_vision_model
from mcp_server.settings import Settings

# Initialize Settings
settings = Settings()

# Configure Logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logger.info(f"Starting MCP Server with Log Level: {settings.log_level}")

# Get version from package metadata
VERSION = version("mcp-sitecheck")

# Initialize MCP
mcp = FastMCP("Site Check Pipeline", version=VERSION)

async def process_single_address(
    session: aiohttp.ClientSession, 
    address: str, 
    dry_run: bool, 
    analysis_prompt: str, 
    analysis_schema: str,
    ctx: Context | None = None
) -> dict[str, Any]:

    result = {
        "Address": address,
        "Status": None,
        "Google_Maps_Link": get_google_maps_link(address),
        "Image_Date": None,
        "Error": None,
        "_images": [],
    }

    # Check Metadata
    try:
        metadata = await check_street_view_metadata(session, address)
        status = metadata.get("status")
        result["Status"] = status
        
        # Always include date and link if available
        result["Image_Date"] = metadata.get("date")

        if status != "OK":
            error_msg = metadata.get("error_message", "No imagery available at this location.")
            result["Error"] = f"Google API: {status}. {error_msg}"
            return result
        
        # Dynamic Street View Links by Direction
        num_images = settings.street_view_image_count
        headings = [int(i * 360 / num_images) for i in range(num_images)]
        
        for heading in headings:
            cardinal = get_cardinal_direction(heading)
            col_name = f"Street_View_{cardinal}_{heading}deg"
            result[col_name] = get_street_view_link(metadata, heading=heading)

        if dry_run:
            return result
    except Exception as e:
        result["Error"] = f"Metadata check failed: {e}"
        return result

    # Fetch Images (360 view) in parallel
    try:
        image_tasks = [fetch_street_view_image(session, address, heading=h) for h in headings]
        image_responses = await asyncio.gather(*image_tasks)
        
        for heading, image_bytes in zip(headings, image_responses):
            if image_bytes:
                result["_images"].append({"bytes": image_bytes, "heading": heading})
        
        if not result["_images"]:
            result["Error"] = "Failed to fetch any image bytes"
            return result
    except Exception as e:
        result["Error"] = f"Image fetch failed: {e}"
        return result

    # Vision Analysis
    try:
        analysis = await analyze_image_with_vision_model(result["_images"], address, analysis_prompt, analysis_schema)
        if "error" in analysis:
            result["Error"] = analysis["error"]
        else:
            result.update(analysis)
    except Exception as e:
        result["Error"] = f"Vision analysis failed: {e}"

    return result

@mcp.tool()
async def process_locations_batch(
    addresses: list[str], 
    analysis_prompt: str,
    analysis_schema: str,
    dry_run: bool = False, 
    output_dir: str = "output",
    ctx: Context = None
) -> str:
    """
    Site Check Pipeline - Processes a batch of structured addresses with 360-degree vision audit.

    Args:
        addresses: A clean, structured list of address strings to process.
        analysis_prompt: MANDATORY: A detailed description of what to look for in the images.
        analysis_schema: MANDATORY: JSON schema string for structured generation.
        dry_run: If True, only checks metadata to save Vision model costs.
        output_dir: The directory where the results will be saved.
        ctx: MCP Context for progress reporting.

    Returns:
        A machine-readable JSON string containing completion status and report paths.
    """
    results = []
    total = len(addresses)
    completed = 0
    
    # Process batch in parallel without restrictions for maximum speed
    async def wrapped_process(session, address):
        nonlocal completed
        res = await process_single_address(session, address, dry_run, analysis_prompt, analysis_schema, ctx)
        completed += 1
        if ctx:
            await ctx.report_progress(completed, total)
        return res

    async with aiohttp.ClientSession() as session:
        tasks = [wrapped_process(session, addr) for addr in addresses]
        results = await asyncio.gather(*tasks)

    for res in results:
        if "_images" in res:
            del res["_images"]

    df = pd.DataFrame(results)
    
    # Calculate Image Age
    now = datetime.now()
    age_strings = []
    age_months_list = []

    for d_str in df.get("Image_Date", []):
        if not d_str or pd.isna(d_str):
            age_strings.append("Unknown")
            age_months_list.append(None)
            continue
        try:
            d = datetime.strptime(str(d_str), "%Y-%m")
            m_diff = (now.year - d.year) * 12 + (now.month - d.month)
            age_months_list.append(m_diff)

            if m_diff < 12:
                age_strings.append(f"{m_diff} month{'s' if m_diff != 1 else ''}")
            else:
                yrs = m_diff // 12
                mos = m_diff % 12
                s = f"{yrs} yr{'s' if yrs != 1 else ''}"
                if mos > 0:
                    s += f" {mos} mo."
                age_strings.append(s)
        except Exception:
            age_strings.append("Unknown")
            age_months_list.append(None)

    if "Image_Date" in df.columns:
        df.insert(df.columns.get_loc("Image_Date") + 1, "Image_Age", age_strings)
    else:
        df["Image_Age"] = age_strings
    df["Image_Age_Months"] = age_months_list

    # Save outputs
    os.makedirs(output_dir, exist_ok=True)
    excel_file = os.path.join(output_dir, "site_check_report.xlsx")
    jsonl_file = os.path.join(output_dir, "site_check_report.jsonl")
    
    df.to_excel(excel_file, index=False)
    
    # Post-process Excel formatting
    try:
        wb = openpyxl.load_workbook(excel_file)
        ws = wb.active
        col_names = [cell.value for cell in ws[1]] if ws else []
        
        # Format Hyperlinks
        for col_name in col_names:
            if col_name == "Google_Maps_Link" or col_name.startswith("Street_View_"):
                col_idx = col_names.index(col_name) + 1
                for row_idx in range(2, ws.max_row + 1):
                    cell = ws.cell(row=row_idx, column=col_idx)
                    if cell.value:
                        url = str(cell.value)
                        if url and not url.startswith('=HYPERLINK'):
                            cell.hyperlink = url
                            cell.value = url
                        cell.style = "Hyperlink"

        # Apply Aging Colors (Row-wide)
        if "Image_Age_Months" in col_names:
            months_col_idx = col_names.index("Image_Age_Months") + 1
            for row_idx in range(2, ws.max_row + 1):
                months_val = ws.cell(row=row_idx, column=months_col_idx).value
                if months_val is not None:
                    m = int(months_val)
                    if m >= 12:
                        # 1 year or older: Red
                        hex_color = "FFFF0000"
                    else:
                        # 0-11 months: Gradual Green to Red
                        # 0 months -> Green (00FF00)
                        # 11 months -> Almost Red
                        r = int((m / 11) * 255)
                        g = int(255 - (m / 11) * 255)
                        hex_color = f"FF{r:02X}{g:02X}00"
                    
                    fill = PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")
                    for col_idx in range(1, len(col_names) + 1):
                        ws.cell(row=row_idx, column=col_idx).fill = fill

        # Delete helper column
        if "Image_Age_Months" in col_names:
            ws.delete_cols(col_names.index("Image_Age_Months") + 1)
        
        wb.save(excel_file)
    except Exception as e:
        print(f"Excel formatting failed: {e}")

    df.drop(columns=["Image_Age_Months"], errors="ignore").to_json(jsonl_file, orient="records", lines=True)

    return json.dumps({
        "status": "completed",
        "count": len(addresses),
        "files": {
            "excel": excel_file,
            "jsonl": jsonl_file
        }
    }, indent=2)

if __name__ == "__main__":
    mcp.run()
