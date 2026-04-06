from typing import Literal
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    gcp_api_key: SecretStr = Field(description="GCP API key for Street View and Maps")
    openrouter_api_key: SecretStr = Field(description="OpenRouter API key")
    vision_model: str = Field(description="Vision model identifier")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(description="Logging level")
    street_view_image_count: int = Field(description="Street View images per location")
