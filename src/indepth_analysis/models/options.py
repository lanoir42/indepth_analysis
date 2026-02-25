from pydantic import BaseModel


class GreeksSnapshot(BaseModel):
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    implied_volatility: float | None = None


class OptionContractData(BaseModel):
    strike: float
    expiry: str
    right: str  # "C" or "P"
    bid: float | None = None
    ask: float | None = None
    volume: int = 0
    open_interest: int = 0
    greeks: GreeksSnapshot = GreeksSnapshot()


class OptionsFlowSummary(BaseModel):
    iv_percentile: float | None = None
    iv_current: float | None = None
    iv_mean_1y: float | None = None
    put_call_ratio: float | None = None
    put_call_oi_ratio: float | None = None
    total_call_volume: int = 0
    total_put_volume: int = 0
    total_call_oi: int = 0
    total_put_oi: int = 0
    unusual_activity: list[str] = []
    max_pain: float | None = None
    near_term_contracts: list[OptionContractData] = []
