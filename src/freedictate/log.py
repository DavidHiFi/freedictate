"""Logging to a rotating file. The app has no console, so this is the only record."""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import traceback

from . import paths

log = logging.getLogger("freedictate")


def setup(debug: bool = False) -> None:
    paths.ensure()
    handler = logging.handlers.RotatingFileHandler(
        paths.LOGS / "freedictate.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    if sys.stderr is not None and not getattr(sys, "frozen", False):
        log.addHandler(logging.StreamHandler())

    def excepthook(kind, value, tb):
        log.critical("Unhandled error:\n%s", "".join(traceback.format_exception(kind, value, tb)))

    def thread_hook(args):
        log.error("Error in thread %s:\n%s", args.thread.name if args.thread else "?",
                  "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
