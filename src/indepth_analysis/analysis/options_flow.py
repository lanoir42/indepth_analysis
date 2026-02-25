import logging
import statistics

from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.options import (
    GreeksSnapshot,
    OptionContractData,
    OptionsFlowSummary,
)

logger = logging.getLogger(__name__)


class OptionsFlowAnalyzer:
    def analyze(
        self,
        chain_data: dict,
        current_price: float | None,
    ) -> tuple[OptionsFlowSummary, SignalWithConfidence]:
        tickers = chain_data.get("tickers", [])
        if not tickers:
            return OptionsFlowSummary(), SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.2,
                rationale="No options data",
            )

        contracts: list[OptionContractData] = []
        call_vol = 0
        put_vol = 0
        call_oi = 0
        put_oi = 0
        ivs: list[float] = []

        for t in tickers:
            c = t.contract
            bid = getattr(t, "bid", None)
            ask = getattr(t, "ask", None)
            vol = getattr(t, "volume", 0) or 0
            oi = getattr(t, "openInterest", 0) or 0

            greeks = GreeksSnapshot()
            mg = getattr(t, "modelGreeks", None)
            if mg:
                greeks = GreeksSnapshot(
                    delta=getattr(mg, "delta", None),
                    gamma=getattr(mg, "gamma", None),
                    theta=getattr(mg, "theta", None),
                    vega=getattr(mg, "vega", None),
                    implied_volatility=getattr(mg, "impliedVol", None),
                )
                iv = getattr(mg, "impliedVol", None)
                if iv and iv > 0:
                    ivs.append(iv)

            ocd = OptionContractData(
                strike=c.strike,
                expiry=c.lastTradeDateOrContractMonth,
                right=c.right,
                bid=bid if bid and bid > 0 else None,
                ask=ask if ask and ask > 0 else None,
                volume=int(vol),
                open_interest=int(oi),
                greeks=greeks,
            )
            contracts.append(ocd)

            if c.right == "C":
                call_vol += int(vol)
                call_oi += int(oi)
            else:
                put_vol += int(vol)
                put_oi += int(oi)

        pc_ratio = put_vol / call_vol if call_vol > 0 else None
        pc_oi_ratio = put_oi / call_oi if call_oi > 0 else None

        iv_current = statistics.mean(ivs) * 100 if ivs else None

        max_pain = self._compute_max_pain(contracts, current_price)

        unusual = self._detect_unusual(contracts, current_price)

        summary = OptionsFlowSummary(
            iv_current=iv_current,
            put_call_ratio=pc_ratio,
            put_call_oi_ratio=pc_oi_ratio,
            total_call_volume=call_vol,
            total_put_volume=put_vol,
            total_call_oi=call_oi,
            total_put_oi=put_oi,
            unusual_activity=unusual,
            max_pain=max_pain,
            near_term_contracts=contracts[:20],
        )

        signal = self._score(summary)
        return summary, signal

    def _compute_max_pain(
        self,
        contracts: list[OptionContractData],
        current_price: float | None,
    ) -> float | None:
        if not contracts or not current_price:
            return None

        strikes = sorted({c.strike for c in contracts})
        if not strikes:
            return None

        min_pain = float("inf")
        max_pain_strike = strikes[0]

        for strike in strikes:
            pain = 0.0
            for c in contracts:
                if c.right == "C" and strike > c.strike:
                    pain += (strike - c.strike) * c.open_interest
                elif c.right == "P" and strike < c.strike:
                    pain += (c.strike - strike) * c.open_interest
            if pain < min_pain:
                min_pain = pain
                max_pain_strike = strike

        return max_pain_strike

    def _detect_unusual(
        self,
        contracts: list[OptionContractData],
        current_price: float | None,
    ) -> list[str]:
        unusual: list[str] = []
        for c in contracts:
            if c.volume > 0 and c.open_interest > 0:
                ratio = c.volume / c.open_interest
                if ratio > 3.0:
                    unusual.append(
                        f"{c.right} {c.strike} {c.expiry}: vol/OI={ratio:.1f}"
                    )
        return unusual[:10]

    def _score(self, summary: OptionsFlowSummary) -> SignalWithConfidence:
        scores: list[float] = []
        reasons: list[str] = []

        if summary.put_call_ratio is not None:
            pcr = summary.put_call_ratio
            if pcr > 1.5:
                scores.append(0.5)
                reasons.append("High P/C ratio (contrarian bullish)")
            elif pcr > 1.0:
                scores.append(0.2)
                reasons.append("Elevated P/C ratio")
            elif pcr < 0.5:
                scores.append(-0.3)
                reasons.append("Low P/C ratio (complacency)")
            else:
                scores.append(0.0)
                reasons.append("Normal P/C ratio")

        if summary.iv_current is not None:
            if summary.iv_current > 60:
                scores.append(-0.3)
                reasons.append("High IV environment")
            elif summary.iv_current < 20:
                scores.append(0.3)
                reasons.append("Low IV environment")

        if summary.unusual_activity:
            reasons.append(f"{len(summary.unusual_activity)} unusual flows")

        if not scores:
            return SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.3,
                rationale="Limited options data",
            )

        avg = sum(scores) / len(scores)
        return SignalWithConfidence(
            signal=Signal.from_score(avg),
            confidence=0.6,
            rationale="; ".join(reasons),
        )
