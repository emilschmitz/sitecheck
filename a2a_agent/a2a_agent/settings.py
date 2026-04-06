from typing import Literal
from pydantic import SecretStr, Field, HttpUrl
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Defaults never go in here.
    Always in .env.sample
    """
    llm_api_key: SecretStr = Field(description="LLM API key")
    llm_base_url: HttpUrl = Field(description="LLM base URL")
    extraction_model: str = Field(description="Extraction model identifier")
    max_steps: int = Field(description="Maximum agentic steps")
    mcp_server_url: HttpUrl = Field(description="MCP server URL")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(description="Logging level")
    enable_traces: bool = Field(description="Enable LLM trace logging")
