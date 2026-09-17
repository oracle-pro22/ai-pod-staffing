"""Server-only configuration. Never expose OCI credentials through the API."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env.local", override=False)
load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class Config:
    provider: str
    model: str
    endpoint: str
    api_format: str
    compartment_id: str
    project_id: str
    config_file: str
    profile: str
    workbook: Path
    reviewer: str
    timeout: float


def config() -> Config:
    provider = os.getenv("AI_PROVIDER", "oci")
    if provider not in {"oci", "demo"}:
        raise ValueError("AI_PROVIDER must be oci or demo.")
    workbook = Path(os.getenv("STAFFING_WORKBOOK_PATH", "data/runtime/staffing.xlsx")).expanduser()
    return Config(
        provider=provider,
        model=os.getenv("OCI_MODEL_ID", "openai.gpt-5.5"),
        endpoint=os.getenv("OCI_GENAI_ENDPOINT", "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com"),
        api_format=os.getenv("OCI_GENAI_API_FORMAT", "native"),
        compartment_id=os.getenv("OCI_COMPARTMENT_ID", ""),
        project_id=os.getenv("OCI_GENAI_PROJECT_OCID", ""),
        config_file=os.path.expanduser(os.getenv("OCI_CONFIG_FILE", "~/.oci/config")),
        profile=os.getenv("OCI_CONFIG_PROFILE", "DEFAULT"),
        workbook=(ROOT / workbook).resolve(),
        reviewer=os.getenv("APP_REVIEWER_NAME", "Indranie B."),
        timeout=min(90, max(1, float(os.getenv("OCI_GENAI_TIMEOUT_MS", "90000")) / 1000)),
    )
