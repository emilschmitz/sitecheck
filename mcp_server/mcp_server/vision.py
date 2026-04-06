import base64
import json
import logging
from typing import Any
import aiohttp
from openai import AsyncOpenAI
from jsonschema import validate, ValidationError
from mcp_server.settings import Settings

settings = Settings()
logger = logging.getLogger(__name__)

openai_client = AsyncOpenAI(
    base_url=str(settings.llm_base_url),
    api_key=settings.llm_api_key.get_secret_value(),
)

async def fetch_street_view_image(
    session: aiohttp.ClientSession, address: str, heading: int = 0
) -> tuple[bytes | None, int]:
    url = "https://maps.googleapis.com/maps/api/streetview"
    params = {
        "size": "400x400",
        "location": address,
        "key": settings.gcp_api_key.get_secret_value(),
        "return_error_code": "true",
        "heading": heading,
    }
    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.read(), 200
        logger.warning(f"Street View image fetch failed for {address} (heading {heading}): {response.status}")
        return None, response.status

async def analyze_image_with_vision_model(
    images: list[dict[str, Any]], address: str, analysis_prompt: str, analysis_schema: str, output_dir: str = None
) -> dict[str, Any]:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Analyze these {len(images)} images of {address} from different angles (360 view).\n{analysis_prompt}"}
            ]
        }
    ]
    
    # Add images to the first message's content
    for img in images:
        base64_image = base64.b64encode(img["bytes"]).decode("utf-8")
        messages[0]["content"].append({
            "type": "text",
            "text": f"Image heading: {img['heading']} degrees"
        })
        messages[0]["content"].append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_image}"
            },
        })

    # Prepare Structured Output Schema
    schema_dict = None
    try:
        schema_dict = json.loads(analysis_schema)
        # OpenAI Structured Outputs require a specific wrapper
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "site_analysis",
                "strict": False,
                "schema": schema_dict
            }
        }
    except Exception as e:
        logger.warning(f"Failed to parse analysis_schema as JSON: {e}. Falling back to json_object.")
        response_format = {"type": "json_object"}

    def make_error_result(error_msg: str) -> dict[str, Any]:
        res = {"error": error_msg, "_validation_error": True}
        if schema_dict and "properties" in schema_dict:
            for prop in schema_dict["properties"]:
                res[prop] = "N/A"
        return res

    # Log Trace: Request
    if settings.enable_traces and output_dir:
        from pathlib import Path
        from datetime import datetime
        trace_dir = Path(output_dir) / "logs" / "vision-lmm-traces"
        trace_dir.mkdir(parents=True, exist_ok=True)
        safe_address = "".join([c if c.isalnum() else "_" for c in address])[:50]
        trace_file = trace_dir / f"{safe_address}_request.json"
        with open(trace_file, "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "address": address,
                "model": settings.vision_model,
                "messages": messages,
                "response_format": response_format
            }, f, indent=2)

    try:
        response = await openai_client.chat.completions.create(
            model=settings.vision_model,
            messages=messages,  # type: ignore
            response_format=response_format, # type: ignore
        )

        content = response.choices[0].message.content

        # Log Trace: Response
        if settings.enable_traces and output_dir:
            trace_file = trace_dir / f"{safe_address}_response.json"
            with open(trace_file, "w") as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "address": address,
                    "content": content
                }, f, indent=2)

        if content is None:
            return make_error_result("Vision analysis returned empty string")
        
        if content.strip().startswith("<!DOCTYPE html>"):
            return make_error_result("Vision analysis failed: API provider returned an HTML error page (likely 502/504)")
            
        try:
            result_data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse vision response as JSON: {e}. Content: {content[:100]}")
            return make_error_result(f"Failed to parse vision response as JSON: {e}")

        # Ensure result_data is a dict before proceeding
        if not isinstance(result_data, dict):
            logger.warning(f"Vision response for {address} was not a dictionary: {type(result_data)}. Resetting to empty dict.")
            result_data = {}
        
        # Validation Logic
        validation_error = False
        if schema_dict:
            try:
                validate(instance=result_data, schema=schema_dict)
            except ValidationError as ve:
                logger.warning(f"Validation failed for {address}: {ve.message}")
                validation_error = True
                
                # Fill missing or invalid fields with "N/A"
                properties = schema_dict.get("properties", {})
                for prop, prop_schema in properties.items():
                    if prop not in result_data:
                        result_data[prop] = "N/A"
                    else:
                        try:
                            # Validate individual property
                            validate(instance=result_data[prop], schema=prop_schema)
                        except ValidationError:
                            result_data[prop] = "N/A"

        result_data["_validation_error"] = validation_error
        return result_data

    except Exception as e:
        logger.error(f"Vision Analysis API failed for '{address}': {e}")
        return make_error_result(f"Failed Vision Analysis: {e}")
