# requires node
# requires jvm
import collections
import functools
import itertools
import operator
import os
import re
import shutil
import socket
import sys
import time
import json
import uuid
import dataclasses
from json import loads
from pathlib import Path
from subprocess import Popen, check_output
from typing import Any, Callable, Dict, Generator, Tuple
from urllib.request import urlopen

import exceptiongroup
import pytest
import requests

from nbconvert_a11y.pytest_axe import Collector, Results, Violation

HERE = Path(__file__).parent


EXCLUDE = re.compile(
    """or with a “role” attribute whose value is “table”, “grid”, or “treegrid”.$"""
    # https://github.com/validator/validator/issues/1125
)


class Base:
    """base class for exceptions and models"""

    def __init_subclass__(cls) -> None:
        dataclasses.dataclass(cls)

    def dict(self):
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

    def dump(self):
        return json.dumps(self.dict())


class Collector(Base):
    """the Axe class is a fluent api for configuring and running accessibility tests."""

    url: str = None
    results: Any = None

    def configure(self):
        return self

    def exception(self):
        return self.results.exception()

    def raises(self):
        exc = self.exception()
        if exc:
            raise exc


class Results(Base):
    data: Any

    def raises(self):
        exc = self.exception()
        if exc:
            raise exc


def get_vnu_path():
    return shutil.which("vnu") or shutil.which("vnu.cmd")


def validate_url(url):
    return loads(
        check_output(
            [get_vnu_path(), "--stdout", "--format", "json", "--exit-zero-always", url]
        )
    )


def validate_path(a_vnu_server_url, path: Path) -> TVnuResults:
    url = f"{a_vnu_server_url}?out=json"
    data = path.read_bytes()
    headers = {"Content-Type": "text/html"}
    res = requests.post(url, data, headers=headers)
    return res.json()


# utilities
def organize_validator_results(results):
    collect = collections.defaultdict(functools.partial(collections.defaultdict, list))
    for (error, msg), group in itertools.groupby(
        results["messages"], key=operator.itemgetter("type", "message")
    ):
        for item in group:
            collect[error][msg].append(item)
    return collect


def raise_if_errors(results, exclude=EXCLUDE):
    collect = organize_validator_results(results)
    exceptions = []
    for msg in collect["error"]:
        if not exclude or not exclude.search(msg):
            exceptions.append(
                exceptiongroup.ExceptionGroup(
                    msg, [Exception(x["extract"]) for x in collect["error"][msg]]
                )
            )
    if exceptions:
        raise exceptiongroup.ExceptionGroup("nu validator errors", exceptions)


def _start_vnu_server(proto: str, host: str) -> Tuple[str, Popen]:
    """Start a vnu HTTP server."""
    port = get_an_unused_port()
    url = f"{proto}://{host}:{port}/"
    server_args = get_vnu_args(host, port)
    url = f"{proto}://{host}:{port}"
    print(f"... starting vnu server at {url}")
    print(">>>", "\t".join(server_args))
    proc = Popen(server_args)
    wait_for_vnu_to_start(url)
    print(f"... vnu server started at {url}")

    return port, url, proc


def wait_for_vnu_to_start(url: str, retries: int = 10, sleep: int = 1):
    last_error = None

    time.sleep(sleep)

    while retries:
        retries -= 1
        try:
            return urlopen(url, timeout=sleep)
        except Exception as err:
            last_error = err
            time.sleep(sleep)

    raise RuntimeError(f"{last_error}")


def get_vnu_args(host: str, port: int):
    win = os.name == "nt"

    java = Path(
        os.environ.get(ENV_JAVA_PATH, shutil.which("java") or shutil.which("java.exe"))
    )
    jar = Path(
        os.environ.get(
            ENV_JAVA_PATH,
            (Path(sys.prefix) / ("Library/lib" if win else "lib") / "vnu.jar"),
        )
    )

    if any(not j.exists() for j in [java, jar]):
        raise RuntimeError(
            "Failed to find java or vnu.jar:\b"
            f"  - {java.exists()} {java}"
            "\n"
            f"  - {jar.exists()} {jar}"
        )

    server_args = [
        java,
        "-cp",
        jar,
        f"-Dnu.validator.servlet.bind-address={host}",
        "nu.validator.servlet.Main",
        port,
    ]

    return list(map(str, server_args))


def get_an_unused_port() -> Callable[[], int]:
    """Find an unused network port (could still create race conditions)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    s.close()
    return port
