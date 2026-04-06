from pydantic import SecretStr, Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gcp_api_key: SecretStr = Field(
        validation_alias=AliasChoices("MCP_GCP_API_KEY", "GCP_API_KEY")
    )
    openrouter_api_key: SecretStr = Field(
        validation_alias=AliasChoices("MCP_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
    )
    vision_model: str = Field(
        default="qwen/qwen3.5-flash-02-23",
        validation_alias=AliasChoices("MCP_VISION_MODEL", "VISION_MODEL")
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
