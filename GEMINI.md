# Project Standards

## Environment Configuration

* Use Pydantic settings for configuration

- **No Hardcoded Defaults**: Do not provide default values for environment variables in the code (e.g., Pydantic `Settings` or `docker-compose.yml`).
- **Single Source of Truth**: All default values must reside exclusively in the `.env.sample` file.
- **Validation**: If a variable is missing at runtime, the application should fail fast with a validation error. This ensures that the production environment is always explicitly configured.
