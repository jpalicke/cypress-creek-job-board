# ABOUTME: Polite fetch settings: refresh interval, per host delay, retries and backoff timing.
# ABOUTME: Also parses a hostile Retry-After header. Jitter is passed in so tests are deterministic.
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

REFRESH_ENV = "CYPRESS_CREEK_FETCH_REFRESH_SECONDS"
HOST_DELAY_ENV = "CYPRESS_CREEK_FETCH_HOST_DELAY_SECONDS"
MAX_RETRIES_ENV = "CYPRESS_CREEK_FETCH_MAX_RETRIES"
MAX_RETRIES_CAP = 8
MAX_BACKOFF_EXPONENT = 62

DELTA_SECONDS = re.compile(r"[0-9]{1,15}")
RETRIES = re.compile(r"[0-9]{1,3}")


class FetchConfigError(ValueError):
    """A fetch setting is unusable. Names the setting, never its value."""


def _check_seconds(name: str, value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class FetchPolicy:
    refresh_interval_seconds: float = 900
    per_host_delay_seconds: float = 1.0
    max_retries: int = 4
    backoff_base_seconds: float = 1.0
    backoff_cap_seconds: float = 60.0

    def __post_init__(self) -> None:
        _check_seconds("refresh_interval_seconds", self.refresh_interval_seconds)
        _check_seconds("per_host_delay_seconds", self.per_host_delay_seconds)
        _check_seconds("backoff_base_seconds", self.backoff_base_seconds)
        _check_seconds("backoff_cap_seconds", self.backoff_cap_seconds)
        retries = self.max_retries
        if (
            isinstance(retries, bool)
            or not isinstance(retries, int)
            or not 0 <= retries <= MAX_RETRIES_CAP
        ):
            raise ValueError(f"max_retries must be an int from 0 to {MAX_RETRIES_CAP}")
        if self.backoff_cap_seconds < self.backoff_base_seconds:
            raise ValueError("backoff_cap_seconds must not be below backoff_base_seconds")

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> "FetchPolicy":
        """Read the settings from env. Unset or blank means the default."""
        defaults = cls()
        try:
            return cls(
                refresh_interval_seconds=_env_seconds(
                    env, REFRESH_ENV, defaults.refresh_interval_seconds
                ),
                per_host_delay_seconds=_env_seconds(
                    env, HOST_DELAY_ENV, defaults.per_host_delay_seconds
                ),
                max_retries=_env_retries(env, MAX_RETRIES_ENV, defaults.max_retries),
            )
        except FetchConfigError:
            raise
        except ValueError as error:
            raise FetchConfigError(f"fetch settings are invalid: {error}") from None

    def backoff_delay(
        self, attempt: int, retry_after_seconds: float | None, jitter: float
    ) -> float:
        """Seconds to wait before retry number attempt (0 based).

        Exponential from the base, capped, then spread by jitter (a caller supplied value in
        [0, 1)) over the upper half of the window. A usable Retry-After wins when larger,
        itself capped.
        """
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
            raise ValueError("backoff attempt must be an int, zero or more")
        if not isinstance(jitter, int | float) or not 0 <= jitter < 1:
            raise ValueError("backoff jitter must be in [0, 1)")
        exponent = min(attempt, MAX_BACKOFF_EXPONENT)
        window = min(self.backoff_cap_seconds, self.backoff_base_seconds * 2**exponent)
        delay = window * (0.5 + 0.5 * jitter)
        if (
            retry_after_seconds is not None
            and math.isfinite(retry_after_seconds)
            and retry_after_seconds > 0
        ):
            delay = max(delay, min(retry_after_seconds, self.backoff_cap_seconds))
        return float(delay)


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name, "").strip()
    return raw or None


def _env_seconds(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _env_value(env, name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise FetchConfigError(f"{name} must be a positive finite number") from None
    try:
        _check_seconds(name, value)
    except ValueError as error:
        raise FetchConfigError(str(error)) from None
    return value


def _env_retries(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _env_value(env, name)
    if raw is None:
        return default
    if not RETRIES.fullmatch(raw) or int(raw) > MAX_RETRIES_CAP:
        raise FetchConfigError(f"{name} must be a whole number from 0 to {MAX_RETRIES_CAP}")
    return int(raw)


def parse_retry_after(raw: str | None, now: datetime) -> float | None:
    """Seconds to wait from a Retry-After header, or None when it is absent or unusable.

    Accepts delta-seconds or an HTTP-date. A date already past means zero seconds.
    """
    if raw is None:
        return None
    text = raw.strip()
    if DELTA_SECONDS.fullmatch(text) and text.isascii():
        return float(text)
    if not text or not text.isascii() or not text.isprintable():
        return None
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    reference = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    seconds = (moment - reference).total_seconds()
    if not math.isfinite(seconds):
        return None
    return max(seconds, 0.0)
