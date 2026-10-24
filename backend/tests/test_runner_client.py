"""RunnerClient edges: host faults are RunnerUnavailable, file refusals RunnerRefused (D-58)."""

import httpx
import pytest

from app.quarantine.runner_client import (
    ProbeFacts,
    RunnerClient,
    RunnerError,
    RunnerRefused,
    RunnerUnavailable,
)
from tests.fakerunner import FakeRunner, film_facts

BASE = "http://sandbox.test"
PATH = "Film/PATH-MARKER/movie.mkv"
BODY_MARKER = "BODY-MARKER-9f3a"


def raw_client(response: httpx.Response | Exception) -> RunnerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    return RunnerClient(BASE, transport=httpx.MockTransport(handler))


async def test_an_unreachable_runner_is_unavailable() -> None:
    fake = FakeRunner()
    fake.script(PATH, film_facts())
    fake.unreachable = True
    client = RunnerClient(BASE, transport=fake.transport)
    with pytest.raises(RunnerUnavailable) as caught:
        await client.probe(PATH)
    assert caught.value.why == "unreachable"


async def test_a_timeout_is_unavailable_with_why_timeout() -> None:
    client = raw_client(httpx.ReadTimeout("slow"))
    with pytest.raises(RunnerUnavailable) as caught:
        await client.probe(PATH)
    assert caught.value.why == "timeout"


@pytest.mark.parametrize(
    ("response", "why"),
    [
        (httpx.Response(503, json={"error": "runner_unavailable", "why": "kvm"}), "kvm"),
        (
            httpx.Response(503, json={"error": "runner_unavailable", "why": "permission"}),
            "permission",
        ),
        (httpx.Response(503, text="<html>down</html>"), "unknown"),
        (httpx.Response(503, json={"why": "KVM; rm -rf /"}), "unknown"),
        (httpx.Response(503, json={"why": "x" * 33}), "unknown"),
        (httpx.Response(503, json=["kvm"]), "unknown"),
        (httpx.Response(500, text="boom"), "server_error"),
        (httpx.Response(502, text="bad gateway"), "server_error"),
        (httpx.Response(418, text="teapot"), "unexpected_status"),
        (httpx.Response(302, headers={"location": "http://evil.test/"}), "unexpected_status"),
    ],
)
async def test_every_non_contract_answer_means_wait(response, why) -> None:
    with pytest.raises(RunnerUnavailable) as caught:
        await raw_client(response).probe(PATH)
    assert caught.value.why == why


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "invalid_path"), (404, "not_found"), (409, "not_regular_file")],
)
async def test_a_refused_path_is_runner_refused_with_the_code(status, code) -> None:
    fake = FakeRunner()
    fake.script(PATH, status)
    client = RunnerClient(BASE, transport=fake.transport)
    with pytest.raises(RunnerRefused) as caught:
        await client.probe(PATH)
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(400, json={"error": "invalid_json"}), "invalid_json"),
        (httpx.Response(400, json={"error": "invalid_path"}), "invalid_path"),
        (httpx.Response(404, json={"error": "not_found"}), "not_found"),
        (httpx.Response(409, json={"error": "not_regular_file"}), "not_regular_file"),
    ],
)
async def test_the_refusal_code_comes_from_the_runners_contract_body(response, code) -> None:
    with pytest.raises(RunnerRefused) as caught:
        await raw_client(response).probe(PATH)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, text="no body"),
        httpx.Response(404, json={"error": "something else"}),
        httpx.Response(404, json={"error": "unknown_route"}),  # a wrong route, not a missing file
        httpx.Response(404, text="<html>nginx</html>"),  # another service behind SANDBOX_URL
        httpx.Response(409, text="x"),
    ],
)
async def test_a_refusal_without_a_contract_code_is_a_host_fault_not_a_file_refusal(
    response,
) -> None:
    """CR-02: only the runner's own error codes can say something about a file."""
    with pytest.raises(RunnerUnavailable) as caught:
        await raw_client(response).probe(PATH)
    assert caught.value.why == "unexpected_status"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"status": "great"}),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, json={**film_facts(), "size_bytes": -1}),
        httpx.Response(200, json={**film_facts(), "streams": "x"}),
        httpx.Response(200, json={**film_facts(), "format": "x"}),
        httpx.Response(200, json={**film_facts(), "size_bytes": True}),
    ],
)
async def test_an_answer_that_breaks_the_contract_is_bad_answer(response) -> None:
    with pytest.raises(RunnerUnavailable) as caught:
        await raw_client(response).probe(PATH)
    assert caught.value.why == "bad_answer"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text=BODY_MARKER),
        httpx.Response(200, json={"status": BODY_MARKER}),
        httpx.Response(503, json={"why": BODY_MARKER}),
        httpx.Response(500, text=BODY_MARKER),
        httpx.Response(418, text=BODY_MARKER),
        httpx.Response(400, json={"error": BODY_MARKER}),
        httpx.Response(404, text=BODY_MARKER),
    ],
)
async def test_exception_text_never_carries_the_body_or_the_path(response) -> None:
    with pytest.raises(RunnerError) as caught:
        await raw_client(response).probe(PATH)
    text = f"{caught.value} {caught.value!r}"
    assert BODY_MARKER not in text
    assert "PATH-MARKER" not in text


async def test_a_transport_error_text_has_no_path() -> None:
    client = raw_client(httpx.ConnectError(f"cannot reach {PATH}"))
    with pytest.raises(RunnerUnavailable) as caught:
        await client.probe(PATH)
    assert "PATH-MARKER" not in str(caught.value)


async def test_health_returns_the_dict_for_a_full_body() -> None:
    fake = FakeRunner()
    client = RunnerClient(BASE, transport=fake.transport)
    body = await client.health()
    assert body["ok"] is True
    assert set(body) >= {"ok", "kvm", "firecracker", "kernel", "alpine", "ffmpeg"}


async def test_health_with_a_missing_key_is_bad_answer() -> None:
    fake = FakeRunner()
    del fake.health_body["kernel"]
    client = RunnerClient(BASE, transport=fake.transport)
    with pytest.raises(RunnerUnavailable) as caught:
        await client.health()
    assert caught.value.why == "bad_answer"


async def test_health_of_a_down_runner_is_unavailable() -> None:
    fake = FakeRunner()
    fake.unreachable = True
    with pytest.raises(RunnerUnavailable):
        await RunnerClient(BASE, transport=fake.transport).health()


async def test_selftest_returns_probe_facts() -> None:
    fake = FakeRunner()
    client = RunnerClient(BASE, transport=fake.transport)
    facts = await client.selftest()
    assert isinstance(facts, ProbeFacts)
    assert facts.status == "ok"


async def test_selftest_host_fault_is_unavailable() -> None:
    fake = FakeRunner()
    fake.script_selftest(("down", "boot"))
    with pytest.raises(RunnerUnavailable) as caught:
        await RunnerClient(BASE, transport=fake.transport).selftest()
    assert caught.value.why == "boot"
