from pydantic import SecretStr, Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    openrouter_api_key: SecretStr = Field(
        validation_alias=AliasChoices("A2A_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
    )
    extraction_model: str = Field(
        default="qwen/qwen3.5-flash-02-23",
        validation_alias=AliasChoices("A2A_EXTRACTION_MODEL", "EXTRACTION_MODEL")
    )
    mcp_server_url: str = Field(
        default="http://mcp-sitecheck:8001/sse",
        validation_alias=AliasChoices("A2A_MCP_SERVER_URL", "MCP_SERVER_URL")
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
