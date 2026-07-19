import time

_last_request: dict[int, float] = {}
MIN_SECONDS_BETWEEN_REQUESTS = 60


def check_rate_limit(user_id: int) -> tuple[bool, int]:
    now = time.time()
    last = _last_request.get(user_id, 0)
    elapsed = now - last
    if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
        return False, int(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_request[user_id] = now
    return True, 0