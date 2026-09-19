"""Every setting the app reads, in one place.

Nothing else in the codebase touches os.environ — if you want to know what can be
configured, this file is the complete answer.
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


class Settings(BaseSettings):
    # --- NVIDIA NIM ---------------------------------------------------------
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    model_reasoning: str = "nvidia/nemotron-3-super-120b-a12b"
    model_fast: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    model_embed: str = "nvidia/nemotron-3-embed-1b"

    # --- documents ----------------------------------------------------------
    source_mode: str = "fixture"          # fixture | web
    tavily_api_key: str = ""

    # --- retrieval ----------------------------------------------------------
    vector_backend: str = "chroma"        # chroma | numpy
    embed_backend: str = "lexical"        # lexical | nemotron
    retrieval_k: int = 4
    retrieval_k_retry: int = 8

    # --- verification -------------------------------------------------------
    support_threshold: float = 0.5
    summary_model: str = "template"      # template | llm

    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    # --- derived paths ------------------------------------------------------
    @property
    def runs_dir(self) -> Path:
        return _ensure(ROOT / "data" / "runs")

    @property
    def cache_dir(self) -> Path:
        return _ensure(ROOT / ".cache")

    @property
    def chroma_dir(self) -> Path:
        return _ensure(ROOT / ".chroma")

    @property
    def fixtures_dir(self) -> Path:
        return ROOT / "eval" / "fixtures"

    @property
    def watchlist_file(self) -> Path:
        return ROOT / "data" / "watchlist.yml"

    @property
    def rules_file(self) -> Path:
        return ROOT / "app" / "rules" / "rules.yml"

    @property
    def prompts_dir(self) -> Path:
        return ROOT / "app" / "prompts"

    @property
    def eval_results_dir(self) -> Path:
        return _ensure(ROOT / "eval" / "results")

    @property
    def has_nvidia_key(self) -> bool:
        return bool(self.nvidia_api_key.strip())


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


settings = Settings()
