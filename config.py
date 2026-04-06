from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class SharedSettings(BaseSettings):
    gcp_api_key: SecretStr
    openrouter_api_key: SecretStr
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

class MCPSettings(SharedSettings):
    vision_model: str

class A2ASettings(SharedSettings):
    extraction_model: str
