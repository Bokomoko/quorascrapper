import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

try:
    from pythonjsonlogger import jsonlogger  # type: ignore
except Exception:  # pragma: no cover
    jsonlogger = None  # type: ignore

_CONFIGURED = False


class _ServiceFilter(logging.Filter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "service"):
            record.service = self.service
        return True


def _build_json_formatter(indent: int | None = None) -> logging.Formatter:
    if jsonlogger is None:
        fmt = "%(asctime)s %(levelname)s %(name)s %(service)s %(message)s"
        return logging.Formatter(fmt=fmt, datefmt="%Y-%m-%dT%H:%M:%S%z")
    fields = [
        "asctime",
        "levelname",
        "name",
        "service",
        "message",
        "module",
        "process",
        "thread",
    ]
    fmt = jsonlogger.JsonFormatter(" ".join([f"%({f})s" for f in fields]))
    if indent and hasattr(fmt, "json_default"):  # type: ignore[attr-defined]
        def _serializer(obj):
            try:
                return json.loads(json.dumps(obj, default=str))
            except Exception:
                return str(obj)

        fmt.json_default = _serializer  # type: ignore[attr-defined]
        fmt.json_encoder = json.JSONEncoder  # type: ignore[attr-defined]
    return fmt


def _build_text_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(service)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def init_logging(service: str, default_level: str = "INFO") -> logging.Logger:
    global _CONFIGURED

    level_name = os.environ.get("LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.environ.get("LOG_FORMAT", "json").lower()
    json_indent = int(os.environ.get("LOG_JSON_INDENT", "0") or 0) or None
    file_enabled = os.environ.get("LOG_FILE_ENABLED", "0") in {"1", "true", "yes"}
    file_path = os.environ.get("LOG_FILE_PATH", f"/logs/{service}.log")
    file_rotate_mb = int(os.environ.get("LOG_FILE_ROTATE_MB", "10"))
    file_backups = int(os.environ.get("LOG_FILE_BACKUPS", "5"))

    root = logging.getLogger()
    root.setLevel(level)

    if not _CONFIGURED:
        for h in list(root.handlers):
            root.removeHandler(h)

        stream_handler = logging.StreamHandler(stream=sys.stdout)
        if log_format == "json":
            stream_handler.setFormatter(_build_json_formatter(json_indent))
        else:
            stream_handler.setFormatter(_build_text_formatter())
        stream_handler.addFilter(_ServiceFilter(service))
        root.addHandler(stream_handler)

        if file_enabled:
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
            except Exception:
                pass
            file_handler = RotatingFileHandler(
                file_path,
                maxBytes=file_rotate_mb * 1024 * 1024,
                backupCount=file_backups,
                encoding="utf-8",
            )
            if log_format == "json":
                file_handler.setFormatter(_build_json_formatter(json_indent))
            else:
                file_handler.setFormatter(_build_text_formatter())
            file_handler.addFilter(_ServiceFilter(service))
            root.addHandler(file_handler)

        _CONFIGURED = True

    return logging.getLogger(service)
