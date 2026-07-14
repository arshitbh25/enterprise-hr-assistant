"""Structured logging (structlog) with request-id correlation.

Every log line — whether emitted by our code or by uvicorn itself — goes
through the same processor pipeline, so a single ``request_id`` ties
together everything that happened while handling one HTTP request
(SDD Section 3.6 / FR-A02).
"""

import contextvars
import logging
import re
import sys

import structlog

from app.core.config import Settings

_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def bind_request_id(request_id: str) -> None:
    """Bind request_id to both the plain contextvar and structlog's context."""
    _request_id_ctx.set(request_id)
    structlog.contextvars.bind_contextvars(request_id=request_id)


def get_request_id() -> str | None:
    """Current request's ID, or None outside of a request (e.g. at startup)."""
    return _request_id_ctx.get()


def clear_request_context() -> None:
    _request_id_ctx.set(None)
    structlog.contextvars.clear_contextvars()


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging once at process startup."""
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.typing.Processor = (
        structlog.dev.ConsoleRenderer()
        if settings.app_env == "local"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.log_level)

    # Route uvicorn's own loggers through the same formatter instead of
    # letting them print unstructured lines alongside our JSON/console output.
    for noisy_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        noisy_logger = logging.getLogger(noisy_logger_name)
        noisy_logger.handlers = [handler]
        noisy_logger.propagate = False


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d{1,3}[\s-]\d{2,4}[\s-]\d{3,4}(?:[\s-]\d{2,4})?)(?!\d)")
_LONG_ID_RE = re.compile(r"\b\d{6,}\b")


def scrub_pii(text: str) -> str:
    """Redact emails, formatted phone numbers, and long numeric IDs (Section 3.6).

    This is a best-effort defense-in-depth scrubber for log output, not a
    general-purpose PII detector: it deliberately requires phone numbers to
    contain a separator (space/hyphen) so it doesn't collide with the
    long-numeric-ID pattern.
    """
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = _LONG_ID_RE.sub("[REDACTED_ID]", text)
    return text
