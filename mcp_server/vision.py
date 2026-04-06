import base64
import json
from typing import Any
import aiohttp
from openai import AsyncOpenAI
from mcp_server.settings import Settings

settings = Settings()

openai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key.get_secret_value(),
)

async def fetch_street_view_image(
    session: aiohttp.ClientSession, address: str
) -> bytes | None:
    url = "https://maps.googleapis.com/maps/api/streetview"
    params = {
        "size": "600x600",
        "location": address,
        "key": settings.gcp_api_key.get_secret_value(),
        "source": "outdoor",
        "return_error_code": "true",
    }
    async with session.get(url, params=params) as response:
        if response.status == 200:
            return await response.read()
        return None

async def analyze_image_with_vision_model(
    image_bytes: bytes, address: str, analysis_prompt: str, analysis_schema: str
) -> dict[str, Any]:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    
    # Combined prompt with schema requirement
    full_prompt = f"{analysis_prompt}\n\nReturn ONLY valid JSON that strictly follows this schema: {analysis_schema}"

    try:
        response = await openai_client.chat.completions.create(
            model=settings.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": full_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            },
                        },
                    ],
                }
            ],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if content is None:
            return {"error": "Vision analysis returned empty string"}
        return json.loads(content)
    except Exception as e:
        print(f"\n⚠️ WARNING: Vision Analysis API failed for '{address}': {e}")
        return {"error": f"Failed Vision Analysis: {e}"}
