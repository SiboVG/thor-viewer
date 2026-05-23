from __future__ import annotations

from abc import ABC, abstractmethod


class TemperatureProvider(ABC):
    @abstractmethod
    def temperature_at_preview_xy(
        self,
        x: int,
        y: int,
        preview_width: int,
        preview_height: int,
    ) -> float | None:
        pass

    @abstractmethod
    def min_temperature(self) -> float | None:
        pass

    @abstractmethod
    def max_temperature(self) -> float | None:
        pass
