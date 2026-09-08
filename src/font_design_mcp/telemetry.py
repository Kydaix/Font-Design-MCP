"""Opt-in local phase measurements. Never record request text or geometry."""

import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

current = ContextVar("font_measurement", default=None)


@contextmanager
def measurement():
    stats = {"phases": {}, "counters": {}}
    token = current.set(stats)
    try:
        yield stats
    finally:
        current.reset(token)


def count(name, amount=1):
    stats = current.get()
    if stats is not None:
        stats["counters"][name] = stats["counters"].get(name, 0) + amount


def phase(name):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                stats = current.get()
                if stats is not None:
                    item = stats["phases"].setdefault(name, {"calls": 0, "seconds": 0})
                    item["calls"] += 1
                    item["seconds"] += time.perf_counter() - started

        return run

    return decorate


def profiled(function):
    @wraps(function)
    def run(*args, **kwargs):
        if current.get() is not None or os.environ.get("FONT_DESIGN_MCP_PROFILE") != "1":
            return function(*args, **kwargs)
        with measurement() as stats:
            try:
                result, images = function(*args, **kwargs)
                count("result_json_bytes", len(result.model_dump_json().encode("utf-8")))
                count("image_bytes", sum(map(len, images)))
                return result, images
            finally:
                logging.warning("font-design-mcp profile %s", json.dumps(stats))

    return run
