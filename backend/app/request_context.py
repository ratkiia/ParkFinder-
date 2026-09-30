"""Per-request context shared with logging (request id for end-to-end traceability)."""

import re
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller-supplied id only if it is short and harmless (prevents log injection).
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex


def resolve_request_id(incoming: str | None) -> str:
    """Reuse a valid incoming id (e.g. from the frontend or a proxy), otherwise generate one."""
    if incoming and REQUEST_ID_PATTERN.match(incoming):
        return incoming
    return new_request_id()
