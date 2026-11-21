# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

"""
Tests for Traffic Signal Cycle Planning and All-Red Parameter Propagation.
Verifies Issue 10 fixes:
- Mathematical correctness of total_full_cycle including yellow and all-red clearance intervals
- Mathematical correctness of red_times and red_yellow_times
- Invariant: green_times[d] + yellow_seconds + all_red_seconds + red_times[d] == total_full_cycle for all d
- Parameter bounds clamping (all_red: 0-10, yellow: 1-10, green_budget: 40-600)
- Backward compatibility when all_red_seconds is omitted
- IPC worker parameter propagation for single image and video analyses
"""

import pytest
from services.planning import (
    DIRECTIONS,
    DEFAULT_GREEN_BUDGET,
    DEFAULT_YELLOW_SECONDS,
    DEFAULT_ALL_RED_SECONDS,
    create_signal_plan,
    calculate_green_times,
)


class TestSignalCyclePlanningCalculations:
    """Mathematical validation of 4-phase traffic cycle calculations."""

    @pytest.mark.parametrize("all_red", [0, 1, 2, 3, 5])
    @pytest.mark.parametrize("yellow", [2, 3, 4])
    @pytest.mark.parametrize("budget", [60, 120, 180])
    def test_cycle_sum_and_phase_invariants(self, all_red: int, yellow: int, budget: int):
        counts = {"North": 25, "South": 15, "East": 10, "West": 5}
        plan = create_signal_plan(
            counts=counts,
            green_budget=budget,
            yellow_seconds=yellow,
            all_red_seconds=all_red,
        )

        total_green = sum(plan["green_times"].values())
        expected_full_cycle = total_green + (yellow + all_red) * len(DIRECTIONS)

        # 1. Total cycle validation
        assert plan["cycle"]["total_green_seconds"] == total_green
        assert plan["cycle"]["yellow_seconds_per_phase"] == yellow
        assert plan["cycle"]["all_red_seconds_per_phase"] == all_red
        assert plan["cycle"]["estimated_full_cycle_seconds"] == expected_full_cycle
        assert plan["yellow_seconds"] == yellow
        assert plan["all_red_seconds"] == all_red

        # 2. Phase-by-phase invariant validation
        for d in DIRECTIONS:
            g = plan["green_times"][d]
            r = plan["red_times"][d]
            ry = plan["red_yellow_times"][d]

            # In a 4-phase ring, when direction d is red, the other 3 phases run their (G_j + Y + AR)
            expected_red = expected_full_cycle - g - yellow - all_red
            expected_ry = expected_full_cycle - g

            assert r == expected_red
            assert ry == expected_ry

            # Every phase must sum exactly to the full cycle time
            assert g + yellow + all_red + r == expected_full_cycle
            # red_yellow_times is red wait + yellow clearance wait
            assert g + ry == expected_full_cycle
            assert r >= 0
            min_floor = max(5, int(budget * 0.10))
            assert g >= min_floor

    def test_concrete_numerical_example(self):
        """
        Verify exact numbers for a known standard case:
        counts = North: 30, South: 10, East: 10, West: 10 (Total: 60)
        budget = 120s, yellow = 3s, all_red = 2s
        Total full cycle = 120 + (3 + 2) * 4 = 120 + 20 = 140s
        """
        counts = {"North": 30, "South": 10, "East": 10, "West": 10}
        plan = create_signal_plan(
            counts=counts,
            green_budget=120,
            yellow_seconds=3,
            all_red_seconds=2,
        )

        assert plan["cycle"]["estimated_full_cycle_seconds"] == 140
        assert plan["cycle"]["all_red_seconds_per_phase"] == 2
        assert plan["cycle"]["yellow_seconds_per_phase"] == 3

        # Check all directions satisfy invariant
        for d in DIRECTIONS:
            g = plan["green_times"][d]
            r = plan["red_times"][d]
            assert g + 3 + 2 + r == 140

    def test_zero_traffic_distribution(self):
        """When zero vehicles are detected, timing divides equally and preserves invariants."""
        counts = {"North": 0, "South": 0, "East": 0, "West": 0}
        plan = create_signal_plan(
            counts=counts,
            green_budget=120,
            yellow_seconds=3,
            all_red_seconds=2,
        )

        expected_full_cycle = 120 + (3 + 2) * 4  # 140
        assert plan["cycle"]["estimated_full_cycle_seconds"] == expected_full_cycle
        for d in DIRECTIONS:
            assert plan["green_times"][d] == 30
            # Red time = 140 - 30 - 3 - 2 = 105s
            assert plan["red_times"][d] == 105
            assert plan["red_yellow_times"][d] == 110
            assert plan["green_times"][d] + 3 + 2 + plan["red_times"][d] == expected_full_cycle

    def test_parameter_clamping(self):
        """Verify inputs outside acceptable bounds are safely clamped."""
        counts = {"North": 10, "South": 10, "East": 10, "West": 10}

        # Negative all_red should clamp to 0
        plan_neg = create_signal_plan(counts, all_red_seconds=-5)
        assert plan_neg["all_red_seconds"] == 0
        assert plan_neg["cycle"]["all_red_seconds_per_phase"] == 0

        # Excessive all_red should clamp to 10
        plan_high = create_signal_plan(counts, all_red_seconds=25)
        assert plan_high["all_red_seconds"] == 10
        assert plan_high["cycle"]["all_red_seconds_per_phase"] == 10

        # Yellow bounds: 1 to 10
        plan_y_low = create_signal_plan(counts, yellow_seconds=0)
        assert plan_y_low["yellow_seconds"] == 1
        plan_y_high = create_signal_plan(counts, yellow_seconds=99)
        assert plan_y_high["yellow_seconds"] == 10

        # Green budget bounds: 40 to 600
        plan_b_low = create_signal_plan(counts, green_budget=10)
        assert plan_b_low["cycle"]["total_green_seconds"] == 40
        plan_b_high = create_signal_plan(counts, green_budget=1000)
        assert plan_b_high["cycle"]["total_green_seconds"] == 600

    def test_default_backward_compatibility(self):
        """When all_red_seconds is omitted, defaults to DEFAULT_ALL_RED_SECONDS (0)."""
        counts = {"North": 5, "South": 5, "East": 5, "West": 5}
        plan = create_signal_plan(counts)
        assert plan["all_red_seconds"] == DEFAULT_ALL_RED_SECONDS
        assert plan["cycle"]["all_red_seconds_per_phase"] == 0
        expected_cycle = DEFAULT_GREEN_BUDGET + (DEFAULT_YELLOW_SECONDS + 0) * len(DIRECTIONS)
        assert plan["cycle"]["estimated_full_cycle_seconds"] == expected_cycle


class TestIPCAllRedPropagation:
    """Verify that all_red_seconds propagates from IPC requests to signal plan."""

    def test_ipc_worker_honors_all_red_seconds(self, monkeypatch, tmp_path):
        import ipc_worker
        from PIL import Image

        test_token = "test_ipc_token_sec_0123456789abcdef"
        monkeypatch.setenv("URBAN_FLOW_IPC_TOKEN", test_token)

        # Create a small valid test image (JPEG with valid magic bytes)
        img_path = tmp_path / "test_ipc.jpg"
        img = Image.new("RGB", (100, 100), color="blue")
        img.save(img_path, format="JPEG")

        # Mock analyse_image to return mock detection results
        def mock_analyse_image(dest_path, upload_dir, **kwargs):
            return {
                "counts": {"North": 12, "South": 8, "East": 4, "West": 2},
                "total_count": 26,
                "annotated_filename": "annotated_test.jpg",
                "detections": [],
                "analysis_note": "Mocked test detection",
            }

        monkeypatch.setattr(ipc_worker, "analyse_image", mock_analyse_image)

        # Test request with custom all_red_seconds = 4
        req = {
            "id": "test_ar_req_1",
            "action": "analyse-image",
            "token": test_token,
            "scope": "inference:write",
            "data": {
                "file_path": str(img_path),
                "junction_name": "IPC Test Junction",
                "green_budget": 120,
                "yellow_seconds": 3,
                "all_red_seconds": 4,
            },
        }

        res = ipc_worker.process_ipc_request(req)
        assert res["ok"] is True
        report = res["result"]
        assert report["all_red_seconds"] == 4
        assert report["cycle"]["all_red_seconds_per_phase"] == 4
        # 120 + (3 + 4) * 4 = 120 + 28 = 148
        assert report["cycle"]["estimated_full_cycle_seconds"] == 148

        # Test request omitting all_red_seconds (backward compatibility)
        req_compat = {
            "id": "test_ar_req_2",
            "action": "analyse-image",
            "token": test_token,
            "scope": "inference:write",
            "data": {
                "file_path": str(img_path),
                "junction_name": "IPC Test Junction",
                "green_budget": 120,
                "yellow_seconds": 3,
            },
        }

        res_compat = ipc_worker.process_ipc_request(req_compat)
        assert res_compat["ok"] is True
        report_compat = res_compat["result"]
        assert report_compat["all_red_seconds"] == 0
        assert report_compat["cycle"]["all_red_seconds_per_phase"] == 0
        # 120 + (3 + 0) * 4 = 132
        assert report_compat["cycle"]["estimated_full_cycle_seconds"] == 132
