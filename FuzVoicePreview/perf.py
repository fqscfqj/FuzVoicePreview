from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PerformanceTrace:
    measurements: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def record_seconds(self, name: str, seconds: float) -> None:
        self.measurements[name] = round(max(0.0, float(seconds)) * 1000.0, 3)

    def record_milliseconds(self, name: str, milliseconds: float) -> None:
        self.measurements[name] = round(max(0.0, float(milliseconds)), 3)

    def record_count(self, name: str, value: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + int(value)

    def extend(self, other: "PerformanceTrace") -> None:
        self.measurements.update(other.measurements)
        self.counters.update(other.counters)

    def lines(self) -> tuple[str, ...]:
        timing_lines = tuple(f"Timing | {name}: {value:.3f} ms" for name, value in self.measurements.items())
        counter_lines = tuple(f"Count | {name}: {value}" for name, value in self.counters.items())
        return timing_lines + counter_lines
