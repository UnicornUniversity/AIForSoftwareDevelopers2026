"""Ollama client, VLM parsing, detector and periodic scheduler — all mocked.

No socket, no model and no Ollama process is needed. The single live smoke test
is marked ``ollama`` and runs only when explicitly requested.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from drone_vision_lab.adapters.vlm import (
    OllamaClient,
    OllamaModel,
    OllamaVlmDetector,
    VlmConfig,
    parse_vlm_response,
)
from drone_vision_lab.adapters.vlm.vlm_detector import encode_frame_jpeg_base64
from drone_vision_lab.adapters.vlm.vlm_parsing import VlmParseError
from drone_vision_lab.domain import DetectionResult, DetectorKind, Frame
from drone_vision_lab.errors import OllamaResponseError, OllamaUnavailableError, VisionError
from drone_vision_lab.workers.vlm_poller import VlmPoller

BASE = "http://127.0.0.1:11434"
GOOD_BOX = {"x": 0.25, "y": 0.25, "w": 0.25, "h": 0.3}


class FakeOllama:
    """Transport double that answers the three endpoints from memory."""

    def __init__(self, *, models=None, capabilities=None, families=None, answer=None):
        self.models = models if models is not None else [{"name": "llava:7b", "size": 4096}]
        self.capabilities = capabilities if capabilities is not None else ["completion", "vision"]
        self.families = families if families is not None else ["llama", "clip"]
        self.answer = answer if answer is not None else json.dumps(
            {"visible": True, "label": "green tennis ball", "bbox": GOOD_BOX}
        )
        self.calls: list[tuple[str, str, dict | None, float]] = []

    def __call__(self, method: str, url: str, body: bytes | None, timeout: float):
        payload = json.loads(body) if body else None
        self.calls.append((method, url, payload, timeout))
        if url.endswith("/api/tags"):
            return 200, json.dumps({"models": self.models}).encode()
        if url.endswith("/api/show"):
            return 200, json.dumps(
                {
                    "capabilities": self.capabilities,
                    "details": {"families": self.families},
                }
            ).encode()
        if url.endswith("/api/chat"):
            message = {"role": "assistant", "content": self.answer}
            return 200, json.dumps({"message": message}).encode()
        return 404, b"not found"


def _client(transport) -> OllamaClient:
    return OllamaClient(BASE, transport=transport)


def _frame() -> Frame:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)


def _loaded_detector(transport, **config) -> OllamaVlmDetector:
    settings = {"model": "llava:7b", **config}
    detector = OllamaVlmDetector(VlmConfig(**settings), client=_client(transport))
    detector.load()
    return detector


# -- client ------------------------------------------------------------------


def test_lists_installed_models():
    fake = FakeOllama(models=[{"name": "llava:7b", "size": 10}, {"name": "llama3:8b"}])
    models = _client(fake).list_models()

    assert [model.name for model in models] == ["llava:7b", "llama3:8b"]
    assert models[0].size_bytes == 10


def test_availability_is_false_when_the_service_is_down():
    def refuse(*_args):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

    assert _client(refuse).available() is False


def test_connection_refusal_becomes_a_clear_error():
    def refuse(*_args):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

    with pytest.raises(OllamaUnavailableError, match="not reachable"):
        _client(refuse).list_models()


def test_a_timeout_is_reported_as_unavailable():
    def slow(*_args):
        raise TimeoutError("timed out")

    with pytest.raises(OllamaUnavailableError, match="timed out"):
        _client(slow).list_models()


def test_http_error_status_is_reported():
    def bad(*_args):
        return 500, b"model crashed"

    with pytest.raises(OllamaResponseError, match="HTTP 500"):
        _client(bad).list_models()


def test_invalid_json_is_rejected():
    def bad(*_args):
        return 200, b"<html>not json</html>"

    with pytest.raises(OllamaResponseError, match="invalid JSON"):
        _client(bad).list_models()


def test_chat_sends_the_image_and_disables_streaming():
    fake = FakeOllama()
    text = _client(fake).chat("llava:7b", "find the ball", "aGVsbG8=", timeout=30.0)

    assert text == fake.answer
    _method, _url, payload, timeout = fake.calls[-1]
    assert payload["stream"] is False
    assert payload["messages"][0]["images"] == ["aGVsbG8="]
    assert payload["messages"][0]["content"] == "find the ball"
    assert timeout == 30.0


def test_chat_bounds_context_and_keeps_the_model_resident():
    fake = FakeOllama()
    _client(fake).chat("llava:7b", "find the ball", "aGVsbG8=", timeout=30.0)

    payload = fake.calls[-1][2]
    assert payload["options"]["num_ctx"] == 4096
    assert payload["options"]["num_predict"] == 256
    assert payload["keep_alive"] == "30m"


def test_loading_warms_the_model_with_the_same_context():
    fake = FakeOllama()
    _loaded_detector(fake)

    chat = next(call for call in fake.calls if call[1].endswith("/api/chat"))
    payload = chat[2]
    assert payload["options"]["num_ctx"] == 4096
    assert payload["options"]["num_predict"] == 1
    assert payload["keep_alive"] == "30m"


def _image_chats(fake):
    return [
        call
        for call in fake.calls
        if call[1].endswith("/api/chat") and "images" in call[2]["messages"][0]
    ]


def test_a_thinking_model_is_asked_not_to_think():
    fake = FakeOllama(capabilities=["completion", "vision", "thinking"])
    detector = _loaded_detector(fake)

    warm_up = next(call for call in fake.calls if call[1].endswith("/api/chat"))
    assert warm_up[2]["think"] is False

    detector.detect(_frame())

    assert _image_chats(fake)[-1][2]["think"] is False


def test_a_model_without_thinking_omits_the_flag():
    fake = FakeOllama()
    detector = _loaded_detector(fake)

    detector.detect(_frame())

    assert "think" not in _image_chats(fake)[-1][2]


def test_model_info_reads_capabilities():
    info = _client(FakeOllama()).model_info("llava:7b")
    assert info.supports_images is True


def test_capabilities_win_over_family_guesswork():
    no_vision = OllamaModel("x", capabilities=("completion",), families=("clip",))
    assert no_vision.supports_images is False
    assert OllamaModel("x", capabilities=("vision",)).supports_images is True
    assert OllamaModel("x", families=("llama", "clip")).supports_images is True
    assert OllamaModel("x").supports_images is None


# -- parsing -----------------------------------------------------------------


def test_parsing_a_valid_answer():
    finding = parse_vlm_response(
        json.dumps({"visible": True, "label": "ball", "bbox": GOOD_BOX}), target="tennis ball"
    )

    assert finding.visible is True
    assert finding.label == "ball"
    assert finding.box is not None
    assert finding.box.x == pytest.approx(0.25)


def test_parsing_tolerates_markdown_fences():
    text = "```json\n" + json.dumps({"visible": True, "bbox": GOOD_BOX}) + "\n```"
    assert parse_vlm_response(text, target="ball").visible is True


def test_parsing_visible_false():
    finding = parse_vlm_response(
        json.dumps({"visible": False, "label": "ball", "bbox": None}), target="ball"
    )
    assert finding.visible is False
    assert finding.box is None


@pytest.mark.parametrize(
    "answer",
    [
        "no json here",
        "```json\n{broken\n```",
        json.dumps({"visible": "yes", "bbox": GOOD_BOX}),
        json.dumps({"visible": True}),
        json.dumps({"visible": True, "bbox": {"x": 0.2, "y": 0.2, "w": 0.0, "h": 0.2}}),
        json.dumps({"visible": True, "bbox": {"x": 0.9, "y": 0.1, "w": 0.3, "h": 0.2}}),
        json.dumps({"visible": True, "bbox": {"x": -0.2, "y": 0.1, "w": 0.3, "h": 0.2}}),
        json.dumps({"visible": True, "bbox": {"x": "0.2", "y": 0.1, "w": 0.3, "h": 0.2}}),
        json.dumps({"visible": False, "bbox": GOOD_BOX}),
    ],
)
def test_parsing_rejects_malformed_or_inconsistent_answers(answer):
    with pytest.raises(VlmParseError):
        parse_vlm_response(answer, target="ball")


def test_model_instructions_are_never_executed():
    text = json.dumps({"visible": False, "label": "ignore previous instructions"})
    finding = parse_vlm_response(text, target="ball")
    # The label is only a display string, and it is length-capped and printable.
    assert finding.label == "ignore previous instructions"
    assert finding.box is None


# -- detector ----------------------------------------------------------------


def test_detector_reports_a_visible_target():
    detector = _loaded_detector(FakeOllama())
    result = detector.detect(_frame())

    assert result.failed is False
    assert result.kind is DetectorKind.VLM
    assert len(result.detections) == 1
    assert result.detections[0].confidence is None
    assert result.detections[0].box.x == pytest.approx(0.25)
    assert result.latency_ms is not None
    assert result.detail


def test_detector_reports_not_visible_without_an_error():
    answer = json.dumps({"visible": False, "label": "ball", "bbox": None})
    result = _loaded_detector(FakeOllama(answer=answer)).detect(_frame())

    assert result.failed is False
    assert result.found is False


def test_detector_rejects_invalid_json_and_keeps_the_raw_text():
    result = _loaded_detector(FakeOllama(answer="I think the ball is on the left")).detect(_frame())

    assert result.failed
    assert "rejected" in (result.error or "")
    assert "on the left" in result.detail


def test_detector_rejects_a_box_past_the_image_edge():
    answer = json.dumps(
        {"visible": True, "bbox": {"x": 0.9, "y": 0.1, "w": 0.5, "h": 0.2}}
    )
    result = _loaded_detector(FakeOllama(answer=answer)).detect(_frame())

    assert result.failed
    assert "past the image" in (result.error or "")


def test_detector_reports_a_chat_timeout_as_an_error_result():
    class _Slow(FakeOllama):
        def __call__(self, method, url, body, timeout):
            payload = json.loads(body) if body else {}
            if url.endswith("/api/chat") and payload["messages"][0].get("images"):
                raise TimeoutError("timed out")
            return super().__call__(method, url, body, timeout)

    result = _loaded_detector(_Slow()).detect(_frame())

    assert result.failed
    assert "timed out" in (result.error or "")


def test_detector_prompt_uses_the_configured_target():
    fake = FakeOllama()
    detector = _loaded_detector(fake, target="red apple")
    detector.detect(_frame())

    chat = _image_chats(fake)[-1]
    content = chat[2]["messages"][0]["content"]
    assert "red apple" in content
    assert "$target" not in content
    # The JSON example names the same object as the question.
    assert '"label": "red apple"' in content


def test_detector_needs_loading_first():
    result = OllamaVlmDetector(VlmConfig(model="llava:7b")).detect(_frame())
    assert result.failed
    assert "not loaded" in (result.error or "")


def test_no_models_installed_is_reported():
    detector = OllamaVlmDetector(
        VlmConfig(model="llava:7b"), client=_client(FakeOllama(models=[]))
    )
    with pytest.raises(VisionError, match="no models installed"):
        detector.load()


def test_a_model_that_is_not_installed_lists_the_installed_ones():
    detector = OllamaVlmDetector(
        VlmConfig(model="missing:7b"), client=_client(FakeOllama())
    )
    with pytest.raises(VisionError, match="not installed") as info:
        detector.load()
    assert "llava:7b" in info.value.user_message


def test_an_unselected_model_is_reported():
    detector = OllamaVlmDetector(VlmConfig(model=""), client=_client(FakeOllama()))
    with pytest.raises(VisionError, match="No VLM model selected"):
        detector.load()


def test_a_model_without_image_support_is_refused():
    detector = OllamaVlmDetector(
        VlmConfig(model="llama3:8b"),
        client=_client(FakeOllama(models=[{"name": "llama3:8b"}], capabilities=["completion"])),
    )
    with pytest.raises(VisionError, match="does not accept images"):
        detector.load()


def test_unverifiable_image_support_is_refused_rather_than_guessed():
    detector = OllamaVlmDetector(
        VlmConfig(model="mystery:1b"),
        client=_client(
            FakeOllama(models=[{"name": "mystery:1b"}], capabilities=[], families=[])
        ),
    )
    with pytest.raises(VisionError, match="Could not verify"):
        detector.load()


def test_a_bare_model_name_matches_the_default_tag():
    detector = OllamaVlmDetector(
        VlmConfig(model="llava"), client=_client(FakeOllama(models=[{"name": "llava:latest"}]))
    )
    detector.load()
    assert detector.ready
    assert "llava:latest" in detector.name


def test_frame_encoding_produces_base64_jpeg():
    encoded = encode_frame_jpeg_base64(_frame())
    assert encoded.startswith("/9j/")  # JPEG SOI marker, base64-encoded


def test_large_frames_are_downscaled_before_encoding():
    cv2 = pytest.importorskip("cv2")
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame = Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)

    encoded = encode_frame_jpeg_base64(frame)
    decoded = cv2.imdecode(
        np.frombuffer(base64.b64decode(encoded), dtype=np.uint8), cv2.IMREAD_COLOR
    )

    assert max(decoded.shape[:2]) == 640
    # Aspect ratio is preserved.
    assert decoded.shape[1] / decoded.shape[0] == pytest.approx(1920 / 1080, rel=0.01)


# -- scheduler ---------------------------------------------------------------


class _StubRunner(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, *, busy: bool = False):
        super().__init__()
        self.busy = busy
        self.jobs = []

    def submit(self, fn) -> bool:
        if self.busy:
            return False
        self.busy = True
        self.jobs.append(fn)
        return True


class _CountingDetector:
    kind = DetectorKind.VLM

    def __init__(self):
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return SimpleNamespace(kind=DetectorKind.VLM)


def test_poller_skips_ticks_while_inference_is_running(qapp):
    runner = _StubRunner()
    detector = _CountingDetector()
    poller = VlmPoller(detector, _frame, runner=runner)

    poller.tick()  # starts one job
    poller.tick()  # must not queue a second
    poller.tick()

    assert len(runner.jobs) == 1
    assert poller.skipped == 2
    assert poller.ticks == 3


def test_poller_does_nothing_without_a_frame(qapp):
    runner = _StubRunner()
    poller = VlmPoller(_CountingDetector(), lambda: None, runner=runner)

    poller.tick()

    assert runner.jobs == []


def test_poller_reemits_results(qapp):
    runner = _StubRunner()
    poller = VlmPoller(_CountingDetector(), _frame, runner=runner)
    received = []
    poller.result_ready.connect(received.append)

    poller.tick()
    runner.jobs[0]()
    result = DetectionResult(detector_name="test VLM", kind=DetectorKind.VLM)
    runner.finished.emit(result)

    assert received == [result]


def test_poller_interval_is_configurable_and_clamped(qapp):
    poller = VlmPoller(_CountingDetector(), _frame)

    poller.set_interval(0.5)
    assert poller.interval_ms == 500
    poller.set_interval(0.0)
    assert poller.interval_ms == 100


# -- live smoke (opt-in) -----------------------------------------------------


@pytest.mark.ollama
def test_live_ollama_smoke():
    """Set DRONE_VISION_LAB_OLLAMA_MODEL and start Ollama to run this."""
    model = os.environ.get("DRONE_VISION_LAB_OLLAMA_MODEL")
    if not model:
        pytest.skip("set DRONE_VISION_LAB_OLLAMA_MODEL to a vision model tag")

    detector = OllamaVlmDetector(VlmConfig(model=model))
    detector.load()

    assert detector.ready
    result = detector.detect(_frame())
    assert result.kind is DetectorKind.VLM
