from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore", hide_input_in_errors=True)

    backend_env: Literal["local", "test", "production"] = "local"
    backend_auth_mode: Literal["oidc", "local"] = "oidc"
    backend_local_token: SecretStr | None = None
    backend_local_subject: str = ""
    staffing_demo_personas_enabled: bool = False
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    db_user: str = "AI_POD_STAFFING"
    db_password: SecretStr | None = None
    db_tns_alias: str = ""
    db_wallet_location: str = ""
    db_wallet_password: SecretStr | None = None
    db_pool_min: int = Field(default=0, ge=0, le=4)
    db_pool_max: int = Field(default=2, ge=1, le=8)
    db_pool_increment: int = Field(default=1, ge=1, le=4)
    oci_config_file: str = "~/.oci/config"
    oci_config_profile: str = "DEFAULT"
    oci_genai_endpoint: str = ""
    oci_genai_compartment_id: str = ""
    oci_genai_model_id: str = ""
    oci_genai_provider: str = ""
    oci_timeout_seconds: int = Field(default=30, ge=5, le=60)
    oci_max_output_tokens: int = Field(default=2048, ge=500, le=4096)
    staffing_worker_enabled: bool = False
    staffing_decisions_enabled: bool = False
    staffing_policy_version: str = "staffing-v1-draft"
    staffing_poll_seconds: int = Field(default=5, ge=1, le=60)
    staffing_lease_seconds: int = Field(default=180, ge=90, le=600)
    staffing_max_candidates: int = Field(default=60, ge=5, le=100)
    staffing_search_limit: int = Field(default=2000, ge=1, le=10000)

    @model_validator(mode="after")
    def check_configuration(self):
        if self.staffing_demo_personas_enabled and (self.backend_env != "local" or self.backend_auth_mode != "local"):
            raise ValueError("Demo personas require local environment and local authentication")
        if self.db_pool_min > self.db_pool_max or self.db_pool_increment > self.db_pool_max:
            raise ValueError("Invalid Oracle pool bounds")
        if self.staffing_lease_seconds < self.oci_timeout_seconds * 2 + 30:
            raise ValueError("Worker lease must exceed two OCI timeouts plus database overhead")
        if self.db_user != "AI_POD_STAFFING":
            raise ValueError("This service is scoped to AI_POD_STAFFING")
        for value in (self.oidc_issuer, self.oidc_jwks_url, self.oci_genai_endpoint):
            if value:
                parsed = urlsplit(value)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
                    raise ValueError("Service URLs must be HTTPS without credentials, queries or fragments")
        if self.oci_genai_endpoint and urlsplit(self.oci_genai_endpoint).path not in ("", "/"):
            raise ValueError("OCI endpoint must be a service origin, without an API path")
        if self.backend_auth_mode == "local":
            if self.backend_env == "production":
                raise ValueError("Local authentication is prohibited in production")
            if (not self.backend_local_token or len(self.backend_local_token.get_secret_value().strip()) < 32
                or (not self.staffing_demo_personas_enabled and not self.backend_local_subject.strip())):
                raise ValueError("Local authentication requires a random token and, outside persona mode, a configured subject")
        if self.backend_env == "production" and not self.oidc_ready:
            raise ValueError("Production requires configured OIDC issuer, audience and JWKS URL")
        return self

    @property
    def oidc_ready(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url)

    @property
    def database_ready(self) -> bool:
        return bool(self.db_password and self.db_password.get_secret_value() and self.db_tns_alias
                    and self.db_wallet_location and self.db_wallet_password
                    and self.db_wallet_password.get_secret_value())

    @property
    def wallet_path(self) -> str:
        return str(Path(self.db_wallet_location).expanduser().resolve())
