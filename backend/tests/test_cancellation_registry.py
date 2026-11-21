# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

import concurrent.futures
import os
import sys
import time
import pytest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from ipc_worker import (
    BoundedCancellationRegistry,
    CANCELLED_REQUESTS,
    cancel_request,
    handle_cancel,
    is_request_cancelled,
    pop_cancelled_request,
    process_ipc_request,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure registry is clean before and after each test."""
    CANCELLED_REQUESTS.clear()
    yield
    CANCELLED_REQUESTS.clear()


# 1. Normal cancellation
def test_normal_cancellation_lifecycle():
    req_id = "req_normal_123"
    assert not is_request_cancelled(req_id)
    assert not pop_cancelled_request(req_id)

    # Cancel request
    cancel_request(req_id)
    assert is_request_cancelled(req_id)
    assert req_id in CANCELLED_REQUESTS

    # Pop consumes cancellation
    assert pop_cancelled_request(req_id)

    # Subsequent checks return False (consumed)
    assert not is_request_cancelled(req_id)
    assert not pop_cancelled_request(req_id)
    assert req_id not in CANCELLED_REQUESTS


# 2. Expired cancellation IDs
def test_expired_cancellation_ids():
    registry = BoundedCancellationRegistry(max_entries=100, ttl_seconds=0.2, cleanup_interval_seconds=0.05)
    registry.add("short_lived_req")
    assert registry.is_cancelled("short_lived_req")

    # Sleep past TTL
    time.sleep(0.25)

    # Checking expired ID should return False and auto-purge it
    assert not registry.is_cancelled("short_lived_req")
    assert "short_lived_req" not in registry
    assert len(registry) == 0


def test_custom_timestamp_expiration():
    registry = BoundedCancellationRegistry(max_entries=100, ttl_seconds=300.0)
    base_time = 1000.0

    registry.add("req_t1", timestamp=base_time)
    assert registry.is_cancelled("req_t1", now=base_time + 100.0)

    # 301 seconds later -> expired
    assert not registry.is_cancelled("req_t1", now=base_time + 301.0)
    assert len(registry) == 0


# 3. Maximum registry capacity (FIFO/LRU eviction)
def test_maximum_registry_capacity():
    max_cap = 5
    registry = BoundedCancellationRegistry(max_entries=max_cap, ttl_seconds=3600.0)

    for i in range(12):
        registry.add(f"req_{i}")
        assert len(registry) <= max_cap

    # Registry size must be exactly max_cap
    assert len(registry) == max_cap

    # Oldest entries (0 to 6) must have been evicted in FIFO order
    for i in range(7):
        assert not registry.is_cancelled(f"req_{i}")

    # Newest entries (7 to 11) must remain active
    for i in range(7, 12):
        assert registry.is_cancelled(f"req_{i}")


# 4. Duplicate cancellation IDs (Idempotence & LRU touch)
def test_duplicate_cancellation_ids():
    registry = BoundedCancellationRegistry(max_entries=10, ttl_seconds=3600.0)

    for _ in range(5):
        registry.add("duplicate_req_1")

    assert len(registry) == 1
    assert registry.is_cancelled("duplicate_req_1")

    # Adding again with new timestamp does not duplicate
    registry.add("duplicate_req_1")
    assert len(registry) == 1
    assert registry.pop("duplicate_req_1")
    assert len(registry) == 0


# 5. Concurrent cancellation requests
def test_concurrent_cancellation_requests():
    registry = BoundedCancellationRegistry(max_entries=5000, ttl_seconds=300.0)
    num_threads = 16
    requests_per_thread = 100

    def worker_cancel(thread_idx: int):
        for j in range(requests_per_thread):
            req_id = f"worker_{thread_idx}_req_{j}"
            registry.add(req_id)
            # concurrent read check
            assert registry.is_cancelled(req_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_cancel, t) for t in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert len(registry) == num_threads * requests_per_thread


# 6. Concurrent registry cleanup
def test_concurrent_registry_cleanup():
    # Registry with very short TTL to induce heavy concurrent purging
    registry = BoundedCancellationRegistry(max_entries=50, ttl_seconds=0.05, cleanup_interval_seconds=0.01)
    stop_flag = False

    def adder():
        count = 0
        while not stop_flag:
            registry.add(f"churn_req_{count}")
            count += 1
            time.sleep(0.005)

    def reader_cleaner():
        while not stop_flag:
            registry.cleanup()
            _ = len(registry)
            time.sleep(0.005)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f1 = executor.submit(adder)
        f2 = executor.submit(reader_cleaner)
        f3 = executor.submit(adder)
        f4 = executor.submit(reader_cleaner)

        time.sleep(0.3)
        stop_flag = True

        f1.result()
        f2.result()
        f3.result()
        f4.result()

    # Registry must remain bounded and strictly less than or equal to max_entries
    assert len(registry) <= 50


# 7. Cancellation of completed requests
def test_cancellation_of_already_completed_requests():
    """When Electron cancels a request after processing has already finished, it does not leak indefinitely."""
    # Temporarily adjust CANCELLED_REQUESTS TTL to test auto-expiry on global singleton
    old_ttl = CANCELLED_REQUESTS.ttl_seconds
    try:
        CANCELLED_REQUESTS.ttl_seconds = 0.1

        # Completed request arrives at cancellation handler
        res = handle_cancel({"cancel_id": "completed_req_999"})
        assert res.get("cancelled") == "completed_req_999"
        assert is_request_cancelled("completed_req_999")

        # Operation has already returned, so pop is never called by the worker.
        # After TTL, it must be pruned cleanly.
        time.sleep(0.15)
        assert not is_request_cancelled("completed_req_999")
        assert len(CANCELLED_REQUESTS) == 0
    finally:
        CANCELLED_REQUESTS.ttl_seconds = old_ttl


# 8. Long-running operation stability & memory bounding
def test_long_running_operation_stability():
    """Simulate long-running high-volume cancellation traffic to verify memory stays strictly bounded."""
    registry = BoundedCancellationRegistry(max_entries=200, ttl_seconds=300.0)

    # Send 10,000 cancellations
    for i in range(10000):
        registry.add(f"stream_req_{i}")
        if i % 500 == 0:
            # Memory size must never exceed 200
            assert len(registry) <= 200

    assert len(registry) == 200
    stats = registry.get_stats()
    assert stats["size"] == 200
    assert stats["max_entries"] == 200


# 9. Set-like compatibility for existing tests
def test_set_compatibility_interface():
    registry = BoundedCancellationRegistry(max_entries=10, ttl_seconds=300.0)
    registry.add("item_1")
    assert "item_1" in registry
    assert "item_2" not in registry

    registry.discard("item_1")
    assert "item_1" not in registry

    # Discard non-existent does not raise
    assert not registry.discard("item_non_existent")

    registry.add("item_3")
    registry.remove("item_3")
    assert "item_3" not in registry

    with pytest.raises(KeyError):
        registry.remove("item_non_existent")


# 10. Pre-cancelled IPC request execution flow
def test_pre_cancelled_ipc_request(monkeypatch):
    test_token = "test_secret_token_1234567890abcdef"
    monkeypatch.setenv("URBAN_FLOW_IPC_TOKEN", test_token)

    cancel_request("precancel_req_1")

    # Mock IPC request with that ID
    req = {
        "id": "precancel_req_1",
        "action": "health",
        "token": test_token,
        "scope": "read",
        "data": {},
    }
    resp = process_ipc_request(req)
    assert resp["ok"] is True
    assert resp["result"] == {"cancelled": True}
    # Consumed
    assert not is_request_cancelled("precancel_req_1")
