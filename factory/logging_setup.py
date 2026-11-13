"""Loguru-based, secret-redacting, run-scoped logging for the research factory.

Design goals
------------
1. Every run writes self-contained logs under ``<out>/logs/`` (human log,
   machine-readable JSONL, error-only log) so an artifact directory is
   auditable without a terminal scrollback.
2. Credentials must never reach a sink. Values are scrubbed by (a) explicit
   secret registration, (b) conservative pattern rules for bearer tokens,
   key/value pairs and known key prefixes, and (c) URL query redaction.
3. Logging is best-effort observability: a logging failure must not abort a
   research run, and logging never substitutes for the audit artifacts.

The module is deliberately dependency-light (loguru only) and safe to import
in tests. ``configure_logging`` is idempotent: re-configuring removes the
handlers installed by the previous call in the same process.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from loguru import logger

REDACTED = "***REDACTED***"
MIN_SECRET_LENGTH = 8
LOG_LEVELS = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")
DEFAULT_ROTATION = "8 MB"
DEFAULT_RETENTION = 5

# Ordered patterns; the first matching rule wins per scan position.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization headers copied into an error or debug message.
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{6,}"), r"\1 " + REDACTED),
    # key=..., "api_key": "...", token: ..., password=...
    (re.compile(
        r"(?i)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?token"
        r"|secret|client[_-]?secret|password|passwd|authorization|session[_-]?id)"
        r"(\s*[\"']?\s*[:=]\s*[\"']?)([^\s\"'&,;)\]}\\]{4,})"),
     lambda m: m.group(1) + m.group(2) + REDACTED),
    # Query-string credentials (Google CSE uses ?key=; never log the full URL).
    (re.compile(r"(?i)([?&](?:key|api_key|access_token|token|cx|secret)=)[^&\s#]+"),
     r"\1" + REDACTED),
    # Vendor key shapes.
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), REDACTED),
    (re.compile(r"\bigw[A-Za-z0-9_\-]{12,}"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), REDACTED),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), REDACTED),
)

_lock = threading.RLock()
_secrets: set[str] = set()
_handler_ids: list[int] = []
_state: dict[str, Any] = {
    "log_dir": None, "level": None, "json_logs": False,
    "console": False, "redactions": 0, "configured_at": None,
}


class RedactionStats:
    """Counters are process-wide so tests can assert scrubbing happened."""

    def __init__(self) -> None:
        self.redactions = 0
        self.secret_registrations = 0


stats = RedactionStats()


def register_secret(value: str | None, *, minimum: int = MIN_SECRET_LENGTH) -> bool:
    """Register a literal credential so it is scrubbed even without a pattern.

    Returns True when the value was registered. Short values are ignored to
    avoid destroying readability of ordinary log lines.
    """
    if not value or not isinstance(value, str):
        return False
    candidate = value.strip()
    if len(candidate) < minimum:
        return False
    with _lock:
        if candidate not in _secrets:
            _secrets.add(candidate)
            stats.secret_registrations += 1
    return True


def register_secrets(values: Any) -> int:
    count = 0
    for value in values or ():
        if register_secret(value):
            count += 1
    return count


def redact(text: str) -> str:
    """Scrub registered secrets and credential-shaped substrings from text."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    with _lock:
        secrets = tuple(sorted(_secrets, key=len, reverse=True))
    for secret in secrets:
        if secret in out:
            out = out.replace(secret, REDACTED)
            stats.redactions += 1
    for pattern, replacement in _PATTERNS:
        out, hits = pattern.subn(replacement, out)
        if hits:
            stats.redactions += hits
    return out


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        redacted = [_redact_value(item) for item in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value


class _RedactedError(Exception):
    """Placeholder that carries a scrubbed message for a real traceback."""


def _redact_record(record: dict) -> bool:
    """Mutate a loguru record in place; returns True to emit the record."""
    record["message"] = redact(str(record.get("message", "")))
    extra = record.get("extra")
    if isinstance(extra, dict) and extra:
        record["extra"] = _redact_value(extra)
    exception = record.get("exception")
    if exception is not None and isinstance(exception, tuple) and len(exception) == 3:
        kind, value, traceback = exception
        if value is not None:
            text = str(value)
            scrubbed = redact(text)
            if scrubbed != text:
                # Keep loguru's RecordException shape (serialize=True needs it) and
                # drop the unpicklable traceback only when a secret was present.
                record["exception"] = _redacted_exception(exception, scrubbed)
    return True


def _redacted_exception(exception: tuple, scrubbed: str):
    try:
        return type(exception)(exception[0], _RedactedError(scrubbed), None)
    except Exception:  # pragma: no cover - unexpected record shape
        return None


class InterceptHandler(logging.Handler):
    """Route stdlib logging (playwright, urllib, http.client) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - thin
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, redact(record.getMessage()))


def install_stdlib_interception(level: int = logging.WARNING) -> None:
    """Replace root handlers so third-party library logs are redacted too."""
    root = logging.getLogger()
    root.handlers = [InterceptHandler()]
    root.setLevel(level)
    for name in ("playwright", "urllib3", "http.client", "asyncio"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def log_dir_for(out: str | os.PathLike[str]) -> Path:
    return Path(out) / "logs"


def _reset_handlers() -> None:
    logger.remove()
    _handler_ids.clear()


def _install_library_default() -> None:
    """Library-safe default: WARNING to stderr, redacted, no background thread.

    A library must not silently enable INFO logging at import time; an explicit
    ``configure_logging``/``configure_for_run`` call installs run sinks instead.
    """
    logger.remove()
    logger.add(sys.stderr, level="WARNING", filter=_redact_record, enqueue=False,
               backtrace=False, diagnose=False,
               format=("<level>{level: <8}</level> | <cyan>{name}</cyan>:"
                       "<cyan>{function}</cyan> - <level>{message}</level>"))


def configure_logging(
    out: str | os.PathLike[str] | None = None,
    *,
    level: str = "INFO",
    json_logs: bool = True,
    console: bool = False,
    secrets: Any = (),
    interception: bool = True,
    rotation: str = DEFAULT_ROTATION,
    retention: int = DEFAULT_RETENTION,
    run_id: str | None = None,
) -> dict:
    """Install run-scoped sinks. Returns a sanitized description for run.json.

    ``out`` None keeps a console-only configuration (useful for probes).
    """
    normalized = str(level).upper()
    if normalized not in LOG_LEVELS:
        raise ValueError("unsupported log level: " + str(level))
    register_secrets(secrets)
    with _lock:
        _reset_handlers()
        _state.update({"log_dir": None, "level": normalized, "json_logs": bool(json_logs),
                       "console": bool(console), "redactions": 0,
                       "configured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        common = dict(level=normalized, filter=_redact_record, enqueue=True,
                      backtrace=False, diagnose=False)
        if console:
            _handler_ids.append(logger.add(
                sys.stderr,
                format=("<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
                        "<cyan>{extra[run_id]}</cyan> | <level>{message}</level>"),
                colorize=True, **common))
        log_dir = None
        if out is not None:
            log_dir = log_dir_for(out)
            log_dir.mkdir(parents=True, exist_ok=True)
            _handler_ids.append(logger.add(
                log_dir / "run.log",
                format=("{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
                        "{extra[run_id]} | {extra[stage]} | {message}"),
                rotation=rotation, retention=retention, encoding="utf-8",
                colorize=False, **common))
            if json_logs:
                _handler_ids.append(logger.add(
                    log_dir / "run.jsonl", serialize=True, rotation=rotation,
                    retention=retention, encoding="utf-8", **common))
            error_common = dict(common, level="ERROR", backtrace=True)
            _handler_ids.append(logger.add(
                log_dir / "errors.log",
                format=("{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
                        "{extra[run_id]} | {extra[stage]} | {message}\n{exception}"),
                rotation=rotation, retention=retention, encoding="utf-8",
                colorize=False, **error_common))
            _state["log_dir"] = str(log_dir)
        if interception:
            install_stdlib_interception()
        logger.configure(extra={"run_id": run_id or "-", "stage": "run"})
    return describe()


def describe() -> dict:
    with _lock:
        files = []
        if _state["log_dir"]:
            files = ["logs/run.log"]
            if _state["json_logs"]:
                files.append("logs/run.jsonl")
            files.append("logs/errors.log")
        return {
            "log_dir": _state["log_dir"],
            "level": _state["level"],
            "json_logs": _state["json_logs"],
            "console": _state["console"],
            "files": files,
            "secrets_registered": stats.secret_registrations,
            "redactions": stats.redactions,
        }


def redaction_count() -> int:
    return stats.redactions



def silence() -> None:
    """Remove every handler; for embedding applications and test processes."""
    _reset_handlers()


_install_library_default()


def configure_for_run(cfg, run_id: str | None = None) -> dict:
    """Convenience wrapper used by the pipeline: reads logging fields off cfg."""
    secrets = [os.getenv(name) for name in (
        "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID",
        "IAGENT_API_KEY", "ARK_API_KEY")]
    description = configure_logging(
        getattr(cfg, "out", None),
        level=getattr(cfg, "log_level", "INFO"),
        json_logs=getattr(cfg, "log_json", True),
        console=getattr(cfg, "log_console", False),
        secrets=secrets,
        run_id=run_id,
    )
    description["run_id"] = run_id
    return description


@contextmanager
def stage(name: str, **extra: Any) -> Iterator[Any]:
    """Log a stage boundary with timing; re-raise failures after logging them."""
    started = time.perf_counter()
    with logger.contextualize(stage=name, **extra):
        logger.info("stage started: {}", name)
        try:
            yield
        except Exception as exc:
            logger.error("stage failed: {} after_ms={} error={}: {}", name,
                         round((time.perf_counter() - started) * 1000, 1),
                         type(exc).__name__, exc)
            raise
        else:
            logger.info("stage finished: {} duration_ms={}", name,
                        round((time.perf_counter() - started) * 1000, 1))


def timed(step: str, **fields: Any):
    """Context manager returning elapsed seconds for a non-raising operation."""

    class _Timer:
        def __init__(self) -> None:
            self.seconds = 0.0

        def __enter__(self) -> "_Timer":
            self._start = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            self.seconds = round(time.perf_counter() - self._start, 3)
            if exc is None:
                logger.debug("{} completed in {}s {}", step, self.seconds,
                             redact(json.dumps(fields, ensure_ascii=False)) if fields else "")
            else:
                logger.debug("{} failed in {}s ({})", step, self.seconds,
                             exc_type.__name__ if exc_type else "error")
            return False

    return _Timer()


def safe_url(url: str | None, *, limit: int = 200) -> str:
    """Strip credentials, query and fragment so a URL is safe to log."""
    if not url:
        return ""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return "<unparsable-url>"
    host = parts.hostname or ""
    if not parts.scheme or not host:
        return "<unparsable-url>"
    path = parts.path or "/"
    text = f"{parts.scheme}://{host}{path}"
    return text[:limit] + ("…" if len(text) > limit else "")


def log_run_summary(manifest: dict) -> None:
    logger.bind(stage="summary").info(
        "run {} status={} rounds={} queries={} fetches={} errors={} stop_reason={}",
        manifest.get("run_id", "-"), manifest.get("status"),
        manifest.get("rounds"), manifest.get("queries_executed"),
        manifest.get("fetches_attempted"), len(manifest.get("errors") or []),
        manifest.get("stop_reason"))
    if manifest.get("errors"):
        for item in manifest["errors"]:
            logger.bind(stage="summary").error("run error: {}", item)


__all__ = [
    "configure_logging", "configure_for_run", "describe", "stage", "timed",
    "safe_url", "redact", "register_secret", "register_secrets",
    "log_run_summary", "redaction_count", "log_dir_for", "LOG_LEVELS", "silence",
    "install_stdlib_interception", "logger", "REDACTED",
]
