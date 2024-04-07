# requires node
# requires jvm
import re
from json import loads
from pathlib import Path
from subprocess import check_output
from typing import Any
from urllib.request import urlopen

import exceptiongroup

from .utils import Collector, Results, Violation, validate_path, validate_url

EXCLUDE = re.compile(
    """or with a “role” attribute whose value is “table”, “grid”, or “treegrid”.$"""
    # https://github.com/validator/validator/issues/1125
)


class Validator(Collector):
    server_url: Any = None

    def run(self):
        if self.server_url:
            self.results = ValidatorResults(validate_path(self.server_url, self.url))
        else:
            self.results = ValidatorResults(validate_url(self.url))
        return self


class ValidatorViolation(Violation):
    type: Any = None
    url: Any = None
    firstLine: Any = None
    lastLine: Any = None
    lastColumn: Any = None
    firstColumn: Any = None
    message: Any = None
    extract: Any = None
    subType: Any = None
    hiliteStart: Any = None
    hiliteLength: Any = None
    map = {}

    @classmethod
    def from_violations(cls, data):
        out = []
        for message in (messages := data.get("messages")):
            out.append(ValidatorViolation(**message))

        return exceptiongroup.ExceptionGroup(f"{len(messages)} html violations", out)

    @classmethod
    def cast(cls, message):
        CSS_START = re.compile(r"""^“\S+”:""")
        t = (ValidatorViolation[message["type"]],)
        if message.get("subType"):
            t += (ValidatorViolation[message.get("subType")],)
        msg = message["message"]
        if msg.startswith("CSS:"):
            msg = msg[5:]
            t += (ValidatorViolation["css"],)
            if CSS_START.match(msg):
                prop, _, msg = msg.partition(": ")
                t += (ValidatorViolation[prop[1:-1]],)
                id = f"""{message["type"]}-{prop[1:-1]}"""
            else:
                id = f"""{message["type"]}-{msg.strip()}"""
        else:
            id = f"""{message["type"]}-{msg.strip()}"""
            msg = message["extract"]
        return cls.map.setdefault(id, type(id, t, {}))


class ValidatorResults(Results):
    def exception(self):
        if self.data["messages"]:
            return ValidatorViolation.from_violations(self.data)
