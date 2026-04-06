from typing import Literal
from pydantic import SecretStr, Field, HttpUrl
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Defaults never go in here.
    Always in .env.sample
    """
    openrouter_api_key: SecretStr = Field(description="OpenRouter API key")
    extraction_model: str = Field(description="Extraction model identifier")
    max_steps: int = Field(description="Maximum agentic steps")
    mcp_server_url: HttpUrl = Field(description="MCP server URL")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(description="Logging level")
