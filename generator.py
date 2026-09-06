"""Random value generation engine.

Pure Python with no Wox imports, so it can be unit tested standalone.
"""

from __future__ import annotations

import secrets
import socket
import string
import sys
import uuid as uuid_lib
from decimal import Decimal

PROFILE_TYPES = ("integer", "decimal", "string", "uuid", "port")
CHARSETS = ("alphanumeric", "letters", "upper", "lower", "digits", "hex", "custom")

PORT_MIN_DEFAULT = 1024
PORT_MAX_DEFAULT = 65535

# Distinct draws before we conclude the value space is exhausted by the
# no-repeat history. History is capped well below this, so hitting the limit
# means the user really has used everything (or the space is huge and the
# chance of a false positive is negligible).
MAX_ATTEMPTS = 10_000

# Ports to probe for availability in a single generation.
PORT_PROBE_LIMIT = 200

# Above this many distinct values a space counts as "practically unlimited"
# for exhaustion checks.
UNLIMITED_SPACE_THRESHOLD = 1_000_000_000

_CHARSET_LABELS = {
    "alphanumeric": string.ascii_letters + string.digits,
    "letters": string.ascii_letters,
    "upper": string.ascii_uppercase,
    "lower": string.ascii_lowercase,
    "digits": string.digits,
    "hex": string.digits + "abcdef",
}


class ProfileError(ValueError):
    """Raised when a profile's rule configuration is invalid."""


class ExhaustedError(Exception):
    """Raised when no-repeat has consumed every value the rule can produce."""


def _text(profile: dict, key: str) -> str:
    value = profile.get(key, "")
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def _bool(profile: dict, key: str) -> bool:
    value = profile.get(key, False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def _int_field(profile: dict, key: str, default: int | None = None) -> int:
    raw = _text(profile, key)
    if not raw:
        if default is None:
            raise ProfileError(f"missing value for {key}")
        return default
    try:
        return int(Decimal(raw))
    except (ValueError, ArithmeticError):
        raise ProfileError(f"{key} is not a number: {raw!r}")


def _decimal_field(profile: dict, key: str, default: Decimal | None = None) -> Decimal:
    raw = _text(profile, key)
    if not raw:
        if default is None:
            raise ProfileError(f"missing value for {key}")
        return default
    try:
        return Decimal(raw)
    except ArithmeticError:
        raise ProfileError(f"{key} is not a number: {raw!r}")


def profile_type(profile: dict) -> str:
    ptype = _text(profile, "Type").lower() or "integer"
    if ptype not in PROFILE_TYPES:
        raise ProfileError(f"unknown type: {ptype!r}")
    return ptype


def is_no_repeat(profile: dict) -> bool:
    return _bool(profile, "NoRepeat")


def space_size(profile: dict) -> int | None:
    """Number of distinct values the rule can produce, or None if effectively unlimited."""
    ptype = profile_type(profile)
    if ptype in ("integer", "port"):
        lo = _int_field(profile, "Min", 0 if ptype == "integer" else PORT_MIN_DEFAULT)
        hi = _int_field(profile, "Max", 100 if ptype == "integer" else PORT_MAX_DEFAULT)
        if lo > hi:
            raise ProfileError("Min must be <= Max")
        return hi - lo + 1
    if ptype == "decimal":
        return None
    if ptype == "uuid":
        return None
    # string
    length = _int_field(profile, "Length", 8)
    if length <= 0:
        raise ProfileError("Length must be positive")
    chars = _charset_chars(profile)
    size = len(chars) ** length
    return None if size > UNLIMITED_SPACE_THRESHOLD else size


def _charset_chars(profile: dict) -> str:
    charset = _text(profile, "Charset").lower() or "alphanumeric"
    if charset not in CHARSETS:
        raise ProfileError(f"unknown charset: {charset!r}")
    if charset == "custom":
        chars = _text(profile, "CustomChars")
        if not chars:
            raise ProfileError("CustomChars is empty")
        return chars
    return _CHARSET_LABELS[charset]


def _randint(lo: int, hi: int) -> int:
    return lo + secrets.randbelow(hi - lo + 1)


def _rand_string(profile: dict, length: int) -> str:
    chars = _charset_chars(profile)
    return "".join(secrets.choice(chars) for _ in range(length))


def _rand_decimal(profile: dict) -> str:
    decimals = _int_field(profile, "Decimals", 2)
    if decimals < 0:
        raise ProfileError("Decimals must be >= 0")
    lo = _decimal_field(profile, "Min", Decimal(0))
    hi = _decimal_field(profile, "Max", Decimal(100))
    if lo > hi:
        raise ProfileError("Min must be <= Max")
    scale = 10**decimals
    lo_i = int((lo * scale).to_integral_value(rounding="ROUND_FLOOR"))
    hi_i = int((hi * scale).to_integral_value(rounding="ROUND_FLOOR"))
    n = _randint(lo_i, hi_i)
    return str(Decimal(n).scaleb(-decimals).quantize(Decimal(1).scaleb(-decimals)))


def is_port_available(port: int) -> bool:
    """Check whether the port can be bound for a TCP service on this machine."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sys.platform == "win32":
            # On Windows SO_REUSEADDR lets two processes share a port, so a
            # real availability check needs SO_EXCLUSIVEADDRUSE instead.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("0.0.0.0", port))
        sock.listen(1)
        return True


def _rand_port(profile: dict) -> str:
    lo = _int_field(profile, "Min", PORT_MIN_DEFAULT)
    hi = _int_field(profile, "Max", PORT_MAX_DEFAULT)
    if lo > hi:
        raise ProfileError("Min must be <= Max")
    for _ in range(PORT_PROBE_LIMIT):
        port = _randint(lo, hi)
        try:
            if is_port_available(port):
                return str(port)
        except OSError:
            continue
    raise ProfileError(f"no available port found in [{lo}, {hi}]")


def _generate_once(profile: dict, ptype: str) -> str:
    if ptype == "integer":
        lo = _int_field(profile, "Min", 0)
        hi = _int_field(profile, "Max", 100)
        if lo > hi:
            raise ProfileError("Min must be <= Max")
        return str(_randint(lo, hi))
    if ptype == "decimal":
        return _rand_decimal(profile)
    if ptype == "string":
        length = _int_field(profile, "Length", 8)
        if length <= 0:
            raise ProfileError("Length must be positive")
        return _rand_string(profile, length)
    if ptype == "uuid":
        return str(uuid_lib.uuid4())
    # port
    return _rand_port(profile)


def generate(profile: dict, exclude: frozenset[str] = frozenset()) -> str:
    """Generate one value following the profile's rule.

    When the profile enables NoRepeat, values in ``exclude`` are avoided.
    Raises ProfileError for invalid rules and ExhaustedError when every
    possible value has already been generated.
    """
    ptype = profile_type(profile)
    no_repeat = is_no_repeat(profile)
    size = space_size(profile) if no_repeat else None
    if size is not None and len(exclude) >= size:
        raise ExhaustedError("all possible values have been generated")

    for _ in range(MAX_ATTEMPTS):
        value = _generate_once(profile, ptype)
        if no_repeat and value in exclude:
            continue
        return value
    raise ExhaustedError("gave up looking for an unused value")


def describe(profile: dict) -> str:
    """Human-readable one-line summary of the rule, e.g. for a result subtitle."""
    ptype = profile_type(profile)
    if ptype == "integer":
        lo = _int_field(profile, "Min", 0)
        hi = _int_field(profile, "Max", 100)
        return f"integer [{lo}, {hi}]"
    if ptype == "decimal":
        decimals = _int_field(profile, "Decimals", 2)
        lo = _decimal_field(profile, "Min", Decimal(0))
        hi = _decimal_field(profile, "Max", Decimal(100))
        return f"decimal [{lo}, {hi}] ({decimals} dp)"
    if ptype == "string":
        length = _int_field(profile, "Length", 8)
        charset = _text(profile, "Charset").lower() or "alphanumeric"
        return f"string len={length} charset={charset}"
    if ptype == "uuid":
        return "uuid v4"
    lo = _int_field(profile, "Min", PORT_MIN_DEFAULT)
    hi = _int_field(profile, "Max", PORT_MAX_DEFAULT)
    return f"port [{lo}, {hi}] + availability check"
