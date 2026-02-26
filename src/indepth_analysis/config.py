from pydantic import BaseModel, Field

SECTOR_ETF_MAP: dict[str, str] = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

DEFAULT_WEIGHTS: dict[str, float] = {
    "fundamental": 0.30,
    "technical": 0.20,
    "options": 0.15,
    "macro": 0.15,
    "sentiment": 0.10,
    "portfolio": 0.10,
}


class AnalysisConfig(BaseModel):
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1
    ibkr_timeout: float = 10.0

    sheets_id: str | None = None
    credentials_path: str | None = None

    history_period: str = "1y"
    history_interval: str = "1d"

    weights: dict[str, float] = Field(default_factory=lambda: DEFAULT_WEIGHTS.copy())


class ReferenceConfig(BaseModel):
    db_path: str = "references/references.db"
    download_dir: str = "references"
    embedding_provider: str = "local"  # "local" or "gemini"
    embedding_model_local: str = "nomic-ai/nomic-embed-text-v2-moe"
    embedding_model_gemini: str = "text-embedding-004"
    chunk_target_tokens: int = 320
    chunk_min_tokens: int = 256
    chunk_max_tokens: int = 384
    cost_limit_usd: float = 0.0  # 0 = unlimited
    session_cost_limit_usd: float = 0.0
