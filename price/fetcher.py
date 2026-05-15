"""Fetch price snapshots with yfinance."""
from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional


@dataclass
class PriceSnapshot:
    ticker: str
    fetched_at: str
    last_close: Optional[float] = None
    prev_close: Optional[float] = None
    change_pct: Optional[float] = None
    currency: Optional[str] = None
    name: Optional[str] = None
    market_cap: Optional[float] = None
    recent_closes: list[dict] = field(default_factory=list)
    presentation_close: Optional[dict] = None
    last_5_closes: list[dict] = field(default_factory=list)
    status: str = "ok"

    def to_row(self) -> dict:
        return {
            "ticker": self.ticker,
            "fetched_at": self.fetched_at,
            "last_close": self.last_close,
            "prev_close": self.prev_close,
            "change_pct": self.change_pct,
            "currency": self.currency,
            "name": self.name,
            "market_cap": self.market_cap,
            "status": self.status,
        }

    def as_dict(self) -> dict:
        return asdict(self)


def failed_snapshot(ticker: str, reason: str) -> PriceSnapshot:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return PriceSnapshot(ticker=ticker, fetched_at=now, status=reason)


def _parse_presentation_month(value: str | None) -> tuple[date, date] | None:
    if not value:
        return None
    try:
        year_text, month_text = value.strip().split(".", 1)
        year = int(year_text)
        month = int(month_text)
    except (AttributeError, ValueError):
        return None
    if not 1 <= month <= 12:
        return None
    if year < 100:
        year += 2000
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _close_entry(index, value: float) -> dict:
    return {"date": index.strftime("%Y-%m-%d"), "close": round(float(value), 4)}


def fetch_price_snapshot(ticker: str, presentation_month: str = "") -> PriceSnapshot:
    """Fetch a latest-price snapshot.

    Failures are returned in ``status`` instead of being raised, so monthly
    publishing can still finish even when a quote provider is unavailable.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snap = PriceSnapshot(ticker=ticker, fetched_at=now)

    if not ticker:
        snap.status = "price lookup skipped: missing ticker"
        return snap

    try:
        import yfinance as yf
    except ImportError:
        snap.status = "price lookup failed: yfinance is not installed"
        return snap

    try:
        symbol = yf.Ticker(ticker)
        presentation_range = _parse_presentation_month(presentation_month)
        if presentation_range:
            start, _end = presentation_range
            hist = symbol.history(
                start=start.isoformat(),
                end=(date.today() + timedelta(days=1)).isoformat(),
                auto_adjust=False,
            )
        else:
            hist = symbol.history(period="10d", auto_adjust=False)
        if (hist is None or hist.empty) and presentation_range:
            hist = symbol.history(period="10d", auto_adjust=False)
        if hist is None or hist.empty:
            snap.status = "price lookup failed: no history"
            return snap

        closes = hist["Close"].dropna()
        if closes.empty:
            snap.status = "price lookup failed: no close price"
            return snap

        last_close = float(closes.iloc[-1])
        snap.last_close = round(last_close, 4)

        if len(closes) >= 2:
            prev_close = float(closes.iloc[-2])
            snap.prev_close = round(prev_close, 4)
            if prev_close:
                snap.change_pct = round((last_close - prev_close) / prev_close * 100, 2)

        snap.last_5_closes = [
            _close_entry(idx, value)
            for idx, value in closes.tail(5).items()
        ]
        snap.recent_closes = [
            _close_entry(idx, value)
            for idx, value in closes.tail(3).items()
        ]
        if presentation_range:
            start, end = presentation_range
            month_closes = closes[
                (closes.index.date >= start)
                & (closes.index.date <= end)
            ]
            if not month_closes.empty:
                presentation_idx = month_closes.index[-1]
                presentation_value = float(month_closes.iloc[-1])
                presentation_close = _close_entry(presentation_idx, presentation_value)
                close_index = closes.index.tolist().index(presentation_idx)
                if close_index > 0:
                    previous_value = float(closes.iloc[close_index - 1])
                    if previous_value:
                        presentation_close["change_pct"] = round(
                            (presentation_value - previous_value) / previous_value * 100,
                            2,
                        )
                snap.presentation_close = presentation_close

        try:
            fast_info = symbol.fast_info
            if isinstance(fast_info, dict):
                snap.currency = fast_info.get("currency")
                market_cap = fast_info.get("market_cap") or fast_info.get("marketCap")
            else:
                snap.currency = getattr(fast_info, "currency", None)
                market_cap = getattr(fast_info, "market_cap", None)
            if market_cap is not None:
                snap.market_cap = float(market_cap)
        except Exception:
            pass
        try:
            info = symbol.info if hasattr(symbol, "info") else {}
            snap.name = info.get("longName") or info.get("shortName")
            snap.currency = snap.currency or info.get("currency")
            if snap.market_cap is None and info.get("marketCap") is not None:
                snap.market_cap = float(info["marketCap"])
        except Exception:
            pass

        snap.status = "ok"
    except Exception as e:
        snap.status = f"price lookup failed: {type(e).__name__}: {e}"

    return snap
