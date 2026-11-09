import pytest
from security_config import GLOBAL_RATE_LIMITER


@pytest.fixture(autouse=True)
def reset_rate_limiter_for_tests():
    """Ensure rate limits do not bleed across test cases."""
    GLOBAL_RATE_LIMITER.reset()
    yield
    GLOBAL_RATE_LIMITER.reset()
