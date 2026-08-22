"""
Strategy Registry
=================
Discovers, registers, and manages strategy instances.
Allows dynamic enabling/disabling of strategies for ablation research.
"""

from typing import Dict, List, Optional
from .base import BaseStrategy


class StrategyRegistry:
    """Central registry of all trading strategies."""

    def __init__(self):
        self._strategies: Dict[str, BaseStrategy] = {}
        self._enabled_strategies: set[str] = set()

    def register(self, strategy: BaseStrategy, enabled: bool = True) -> None:
        self._strategies[strategy.name] = strategy
        if enabled:
            self._enabled_strategies.add(strategy.name)

    def enable(self, name: str) -> None:
        if name in self._strategies:
            self._enabled_strategies.add(name)

    def disable(self, name: str) -> None:
        self._enabled_strategies.discard(name)

    def get_enabled(self) -> List[BaseStrategy]:
        return [s for name, s in self._strategies.items() if name in self._enabled_strategies]

    def get_all(self) -> List[BaseStrategy]:
        return list(self._strategies.values())

    def get(self, name: str) -> Optional[BaseStrategy]:
        return self._strategies.get(name)


_global_registry: Optional[StrategyRegistry] = None


def get_strategy_registry() -> StrategyRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = StrategyRegistry()
    return _global_registry
