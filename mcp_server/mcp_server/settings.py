from typing import Literal
from pydantic import SecretStr, Field, HttpUrl
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    gcp_api_key: SecretStr = Field(description="GCP API key for Street View and Maps")
    llm_api_key: SecretStr = Field(description="LLM API key")
    llm_base_url: HttpUrl = Field(description="LLM base URL")
    vision_model: str = Field(description="Vision model identifier")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(description="Logging level")
    enable_traces: bool = Field(description="Enable LLM trace logging")
    street_view_image_count: int = Field(description="Street View images per location")
    default_timeout: int = Field(description="Default timeout for batch processing in seconds")
