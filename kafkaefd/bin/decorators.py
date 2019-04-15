import time
import logging
from functools import wraps

__all__ = ('time_this')

logger = logging.getLogger('kafkaefd')


def time_this(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start
        logger.debug(f"Time for {func.__name__}: {duration:.6f}s")

        return result
    return wrapper
