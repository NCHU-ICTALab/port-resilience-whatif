"""Run the dependency-free first scheduling baseline."""

from __future__ import annotations

import json
from dataclasses import asdict

from .baselines import schedule_public_priority
from .model import Berth, BerthOutage, SafetyWindow, Vessel


def build_demo() -> tuple[tuple[Vessel, ...], tuple[Berth, ...], tuple[SafetyWindow, ...], tuple[BerthOutage, ...]]:
    berths = (
        Berth("1068", 300, 14.0, frozenset({"container"})),
        Berth("1069", 320, 14.5, frozenset({"container"})),
        Berth("1070", 340, 15.0, frozenset({"container"})),
    )
    vessels = (
        Vessel("M001", "military", 5.0, 5.0, 4.0, 180, 8.0, "container", "1068", 7.5),
        Vessel("V023", "commercial", 4.0, 4.0, 8.0, 250, 11.0, "container", "1068"),
        Vessel("V024", "commercial", 5.5, 5.5, 6.0, 220, 10.0, "container", "1069"),
        Vessel("V025", "commercial", 8.0, 8.0, 5.0, 200, 9.0, "container", "1070"),
    )
    windows = (
        SafetyWindow("window-a", 6.0, 7.5, 5, 15),
        SafetyWindow("window-b", 12.0, 13.5, 5, 15),
        SafetyWindow("window-c", 18.0, 19.0, 3, 15),
    )
    outages = (BerthOutage("1068", 10.0, 58.0),)
    return vessels, berths, windows, outages


def main() -> None:
    result = schedule_public_priority(*build_demo())
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
