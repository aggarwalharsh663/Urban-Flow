# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

import pytest
from security_config import GLOBAL_RATE_LIMITER


@pytest.fixture(autouse=True)
def reset_rate_limiter_for_tests():
    """Ensure rate limits do not bleed across test cases."""
    GLOBAL_RATE_LIMITER.reset()
    yield
    GLOBAL_RATE_LIMITER.reset()
