from __future__ import annotations

import uuid
from datetime import datetime, timezone

DIRECTIONS = ("North", "South", "East", "West")
DEFAULT_GREEN_BUDGET = 120
DEFAULT_YELLOW_SECONDS = 3
DEFAULT_ALL_RED_SECONDS = 2


def calculate_green_times(
    counts: dict[str, int],
    green_budget: int = DEFAULT_GREEN_BUDGET,
) -> dict[str, int]:
    """Allocate exact green_budget seconds proportionally with adaptive floor and cap."""
    if set(counts) != set(DIRECTIONS):
        raise ValueError("Counts must include North, South, East, and West.")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values()):
        raise ValueError("Vehicle counts must be non-negative integers.")

    green_budget = max(40, min(600, int(green_budget)))
    min_floor = max(5, int(green_budget * 0.10))
    max_cap = min(int(green_budget * 0.65), green_budget - (len(DIRECTIONS) - 1) * min_floor)

    times = {direction: min_floor for direction in DIRECTIONS}
    remaining = green_budget - sum(times.values())
    weights = {direction: counts[direction] for direction in DIRECTIONS}

    while remaining > 0:
        active = [direction for direction in DIRECTIONS if times[direction] < max_cap]
        if not active:
            for direction in DIRECTIONS:
                if remaining <= 0:
                    break
                times[direction] += 1
                remaining -= 1
            break

        active_weight = sum(weights[direction] for direction in active)
        if active_weight == 0:
            weights = {direction: 1 for direction in active}
            active_weight = len(active)

        shares = {direction: remaining * weights[direction] / active_weight for direction in active}
        capped = [
            direction
            for direction in active
            if shares[direction] >= max_cap - times[direction]
        ]
        if capped:
            for direction in capped:
                allowance = max_cap - times[direction]
                times[direction] += allowance
                remaining -= allowance
                weights[direction] = 0
            continue

        floors = {direction: int(shares[direction]) for direction in active}
        for direction, seconds in floors.items():
            times[direction] += seconds
        remainder = remaining - sum(floors.values())
        ranking = sorted(
            active,
            key=lambda direction: (shares[direction] - floors[direction], weights[direction], -DIRECTIONS.index(direction)),
            reverse=True,
        )
        for direction in ranking[:remainder]:
            times[direction] += 1
        remaining = 0

    return times


def create_signal_plan(
    counts: dict[str, int],
    junction_name: str = "Demo Junction",
    source: str = "simulated",
    original_url: str | None = None,
    annotated_url: str | None = None,
    detection_count: int | None = None,
    detections: list[dict] | None = None,
    analysis_note: str | None = None,
    analysis_provider: str | None = None,
    green_budget: int = DEFAULT_GREEN_BUDGET,
    yellow_seconds: int = DEFAULT_YELLOW_SECONDS,
    all_red_seconds: int = DEFAULT_ALL_RED_SECONDS,
) -> dict:
    green_budget = max(40, min(600, int(green_budget)))
    yellow_seconds = max(1, min(10, int(yellow_seconds)))
    all_red_seconds = max(0, min(10, int(all_red_seconds)))

    green_times = calculate_green_times(counts, green_budget=green_budget)
    busiest = max(DIRECTIONS, key=lambda direction: (counts[direction], -DIRECTIONS.index(direction)))
    total_green = sum(green_times.values())
    total_full_cycle = total_green + len(DIRECTIONS) * (yellow_seconds + all_red_seconds)

    return {
        "report_id": uuid.uuid4().hex,
        "junction_name": junction_name.strip() or "Demo Junction",
        "analysed_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "counts": counts,
        "total_vehicle_count": sum(counts.values()),
        "model_detection_count": detection_count,
        "green_times": green_times,
        "status": {
            direction: "Low" if counts[direction] < 5 else "Medium" if counts[direction] < 15 else "High"
            for direction in DIRECTIONS
        },
        "explanation": (
            (
                f"No vehicles were entered, so each approach received an equal {green_times[DIRECTIONS[0]]}-second green time."
                if source == "simulated"
                else f"No vehicles were detected in any direction, so each approach received an equal {green_times[DIRECTIONS[0]]}-second green time."
            )
            if sum(counts.values()) == 0
            else f"{busiest} received {green_times[busiest]} seconds ({round(green_times[busiest] / total_green * 100)}% of the {total_green}s green budget) "
            f"because it had the highest detected traffic volume ({counts[busiest]} vehicles)."
        ),
        "cycle": {
            "total_green_seconds": total_green,
            "yellow_seconds_per_phase": yellow_seconds,
            "all_red_seconds_per_phase": all_red_seconds,
            "estimated_full_cycle_seconds": total_full_cycle,
        },
        "original_url": original_url,
        "annotated_url": annotated_url,
        "detections": detections or [],
        "analysis_note": analysis_note,
        "analysis_provider": analysis_provider,
        "safety_note": f"Configurable plan ({total_green}s green budget, {total_full_cycle}s total cycle). Timings require validation by traffic authorities.",
    }
