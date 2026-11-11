"""
MT5 Symbol Normalization Map
============================
Maps Zia Quant canonical asset symbols to broker-specific MetaTrader 5 symbols
(handling common broker suffixes such as `.r`, `m`, `.pro`, or explicit overrides).
"""

from typing import Dict, Iterable, Optional

DEFAULT_MT5_SYMBOLS: tuple[str, ...] = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "XAUUSD",
    "XAGUSD",
)


def normalize_canonical(symbol: str) -> str:
    return symbol.replace("/", "").replace(" ", "").upper()


class SymbolMapper:
    """Resolves canonical Zia Quant symbols to local broker symbol names."""

    def __init__(
        self,
        explicit_map: Optional[Dict[str, str]] = None,
        suffix: str = "",
        prefix: str = "",
    ):
        self.explicit_map: Dict[str, str] = {
            normalize_canonical(k): str(v) for k, v in (explicit_map or {}).items()
        }
        self.suffix = suffix or ""
        self.prefix = prefix or ""

    def resolve(
        self,
        canonical_symbol: str,
        available_broker_symbols: Optional[Iterable[str]] = None,
    ) -> Optional[str]:
        canon = normalize_canonical(canonical_symbol)
        avail_list = list(available_broker_symbols) if available_broker_symbols is not None else None

        if canon in self.explicit_map:
            candidate = self.explicit_map[canon]
            if avail_list is None or candidate in avail_list:
                return candidate

        direct = f"{self.prefix}{canon}{self.suffix}"
        if avail_list is None:
            return direct
        if direct in avail_list:
            return direct
        if canon in avail_list:
            return canon

        # Exact prefix match fallback (e.g., EURUSD -> EURUSDm or EURUSD.a)
        matches = [s for s in avail_list if s.upper().startswith(canon)]
        if matches:
            matches.sort(key=len)
            return matches[0]
        return None

