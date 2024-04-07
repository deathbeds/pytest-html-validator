import pytest, requests, shutil, time, uuid, os
from subprocess import Popen
from pathlib import Path
from typing import Any, Callable, Dict, Generator
from .validator import Validator
from .utils import _start_vnu_server

ENV_JAVA_PATH = "NBA11Y_JAVA_PATH"
ENV_VNU_JAR_PATH = "NBA11Y_VNU_JAR_PATH"
ENV_VNU_SERVER_URL = "NBA11Y_VNU_SERVER_URL"

TVnuResults = Dict[str, Any]
TVnuValidator = Callable[[Path], TVnuResults]


@pytest.fixture()
def validate_html_url():
    def go(url):
        return Validator(url=url)

    return go


@pytest.fixture()
def validate_html_path(a_vnu_server_url: str) -> TVnuValidator:
    def go(url):
        return Validator(url=url, server_url=a_vnu_server_url)

    return go


@pytest.fixture(scope="session")
def validate_html_file(a_vnu_server_url: str) -> TVnuValidator:
    """Wrap the nvu validator REST API in a synchronous request

    https://github.com/validator/validator/wiki/Service-%C2%BB-Input-%C2%BB-POST-body
    """

    def post(path: Path | str) -> TVnuResults:
        url = f"{a_vnu_server_url}?out=json"
        data = path.read_bytes()
        headers = {"Content-Type": "text/html"}
        res = requests.post(url, data, headers=headers)
        return res.json()

    return post


@pytest.fixture(scope="session")
def a_vnu_server_url(
    worker_id: str, tmp_path_factory: pytest.TempPathFactory
) -> Generator[None, None, str]:
    """Get the URL for a running VNU server."""
    url: str | None = os.environ.get(ENV_VNU_SERVER_URL)

    if url is not None:
        return url

    proc: Popen | None = None
    owns_lock = False
    proto = "http"
    host = "127.0.0.1"
    root_tmp_dir = tmp_path_factory.getbasetemp().parent
    lock_dir = root_tmp_dir / "vnu_server"
    needs_lock = lock_dir / f"test-{uuid.uuid4()}"

    if worker_id == "master":
        port, url, proc = _start_vnu_server(proto, host)
        owns_lock = True
    else:
        port = None
        retries = 10

        try:
            lock_dir.mkdir()
            owns_lock = True
        except:
            pass

        needs_lock.mkdir()

        if owns_lock:
            port, url, proc = _start_vnu_server(proto, host)
            (lock_dir / f"port-{port}").mkdir()
        else:
            while retries:
                retries -= 1
                try:
                    port = int(next(lock_dir.glob("port-*")).name.split("-")[-1])
                    url = f"{proto}://{host}:{port}"
                except:
                    time.sleep(1)
            if port is None and not retries:
                raise RuntimeError("Never started vnu server")

    yield url

    if needs_lock.exists():
        shutil.rmtree(needs_lock)

    if owns_lock:
        while True:
            needs = [*lock_dir.glob("test-*")]
            if needs:
                time.sleep(1)
                continue
            break

        print(f"... tearing down vnu server at {url}")
        proc.terminate()
        if lock_dir.exists():
            shutil.rmtree(lock_dir)
