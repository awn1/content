from decorator import decorator
from retry.api import retry_call

from infra.utils.time_utils import time_now
import logging
logger = logging.getLogger(__name__)


def retry(exceptions=(AssertionError,), tries=0, delay=-1, max_delay=None, backoff=1, jitter=0,
          logger=logger, raise_original_exception=False):
    @decorator
    def retry_decorator(f, *args, **kwargs):
        start_time = time_now()
        try:
            return retry_call(
                f,
                fargs=args,
                fkwargs=kwargs,
                exceptions=exceptions,
                tries=tries,
                delay=delay,
                max_delay=max_delay,
                backoff=backoff,
                jitter=jitter,
                logger=logger,
            )
        except Exception as e:
            if raise_original_exception:
                raise
            msg = getattr(e, 'msg', str(e))
            run_duration = start_time.diff(time_now(), abs=True).as_interval().in_words()
            raise Exception(f'After {run_duration}, {msg}') from e

    return retry_decorator
