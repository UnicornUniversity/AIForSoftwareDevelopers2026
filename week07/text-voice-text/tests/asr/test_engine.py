from __future__ import annotations

import numpy as np
import pytest

from src import config
from src.asr.tokens import MissingHFTokenError
from src.asr.whisperx.engine import (
    EngineOptions,
    ModelDownloadError,
    UnsupportedDeviceError,
    WhisperXDependencyError,
    collect_speaker_labels,
    default_compute_type,
    dependency_versions,
    resolve_device,
    run_engine,
)


def _options(**overrides) -> EngineOptions:
    base = dict(
        audio=np.zeros(16_000, dtype=np.float32),
        model="small.en",
        language="en",
        device="cpu",
        align=True,
        diarize=True,
    )
    base.update(overrides)
    return EngineOptions(**base)


class FakeModel:
    def __init__(self) -> None:
        self.kwargs = {}

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        return {
            "language": "en",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": " Hello there.",
                    "words": [{"word": "Hello", "start": 0.0, "end": 0.5}],
                }
            ],
        }


class FakeDiarizationPipeline:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def __call__(self, audio, **kwargs):
        return "fake-diarization"


class FakeWhisperX:
    def __init__(self) -> None:
        self.model = FakeModel()
        self.load_model_kwargs = {}
        self.align_args = ()
        self.pipeline_kwargs = {}

    def load_model(self, model, **kwargs):
        self.load_model_kwargs = {"model": model, **kwargs}
        return self.model

    def load_align_model(self, language_code, device, model_name=None, **kwargs):
        return "align-model", {"language": language_code, "dictionary": {}}

    def align(self, segments, model, metadata, audio, device, **kwargs):
        self.align_args = (segments, model, metadata, audio, device)
        return {"segments": segments}

    def DiarizationPipeline(self, **kwargs):
        self.pipeline_kwargs = kwargs
        return FakeDiarizationPipeline(**kwargs)

    def assign_word_speakers(self, diarization, result, **kwargs):
        for segment in result["segments"]:
            segment["speaker"] = "SPEAKER_00"
            for word in segment.get("words", []):
                word["speaker"] = "SPEAKER_00"
        return result


def test_auto_resolves_to_cpu_or_cuda() -> None:
    assert resolve_device("auto", cuda_available=lambda: False) == "cpu"
    assert resolve_device("auto", cuda_available=lambda: True) == "cuda"
    assert resolve_device("cpu", cuda_available=lambda: True) == "cpu"
    assert resolve_device("cuda", cuda_available=lambda: True) == "cuda"


def test_cuda_without_a_gpu_has_a_clear_error() -> None:
    with pytest.raises(UnsupportedDeviceError) as excinfo:
        resolve_device("cuda", cuda_available=lambda: False)
    assert "CUDA" in str(excinfo.value)
    assert "--device cpu" in str(excinfo.value)


def test_unknown_device_is_rejected() -> None:
    with pytest.raises(UnsupportedDeviceError):
        resolve_device("mps", cuda_available=lambda: False)


def test_default_compute_type_follows_device() -> None:
    assert default_compute_type("cpu") == config.WHISPERX_CPU_COMPUTE_TYPE
    assert default_compute_type("cuda") == config.WHISPERX_CUDA_COMPUTE_TYPE


def test_float16_on_cpu_is_rejected_before_loading() -> None:
    with pytest.raises(WhisperXDependencyError, match="needs CUDA"):
        run_engine(
            _options(compute_type="float16"),
            env={"HF_TOKEN": "hf_test"},
            module=FakeWhisperX(),
            cuda_available=lambda: False,
        )


def test_full_fake_pipeline_preserves_anonymous_labels() -> None:
    wx = FakeWhisperX()
    result = run_engine(
        _options(),
        env={"HF_TOKEN": "hf_test"},
        module=wx,
        cuda_available=lambda: False,
    )
    assert result.device == "cpu"
    assert result.compute_type == config.WHISPERX_CPU_COMPUTE_TYPE
    assert result.language == "en"
    assert result.speaker_labels == ("SPEAKER_00",)
    assert result.raw["segments"][0]["speaker"] == "SPEAKER_00"
    assert wx.load_model_kwargs["model"] == "small.en"
    assert wx.load_model_kwargs["device"] == "cpu"
    assert wx.model.kwargs["batch_size"] == config.WHISPERX_BATCH_SIZE
    assert wx.model.kwargs["task"] == "transcribe"
    assert wx.pipeline_kwargs["token"] == "hf_test"
    assert "load_model" in result.timings
    assert "transcribe" in result.timings
    assert "align" in result.timings
    assert "diarize" in result.timings
    assert result.versions["whisperx"]


def test_missing_token_is_checked_before_loading_a_model() -> None:
    class ExplodingWhisperX(FakeWhisperX):
        def load_model(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("model must not be loaded without a token")

    with pytest.raises(MissingHFTokenError):
        run_engine(
            _options(),
            env={},
            module=ExplodingWhisperX(),
            cuda_available=lambda: False,
        )


def test_no_diarization_needs_no_token() -> None:
    result = run_engine(
        _options(diarize=False),
        env={},
        module=FakeWhisperX(),
        cuda_available=lambda: False,
    )
    assert result.speaker_labels == ()
    assert result.diarization_model is None
    assert "diarize" not in result.timings


def test_download_failure_is_reported_clearly() -> None:
    class OfflineWhisperX(FakeWhisperX):
        def load_model(self, *args, **kwargs):
            raise OSError("Connection timed out while downloading")

    with pytest.raises(ModelDownloadError) as excinfo:
        run_engine(
            _options(diarize=False),
            env={},
            module=OfflineWhisperX(),
            cuda_available=lambda: False,
        )
    message = str(excinfo.value)
    assert "download" in message.lower()
    assert "network" in message.lower()


def test_gated_diarization_failure_mentions_model_conditions() -> None:
    class GatedPipeline(FakeDiarizationPipeline):
        def __call__(self, audio, **kwargs):
            raise RuntimeError("401 Client Error: gated model")

    class GatedWhisperX(FakeWhisperX):
        def DiarizationPipeline(self, **kwargs):
            return GatedPipeline(**kwargs)

    with pytest.raises(ModelDownloadError) as excinfo:
        run_engine(
            _options(),
            env={"HF_TOKEN": "hf_test"},
            module=GatedWhisperX(),
            cuda_available=lambda: False,
        )
    assert "conditions" in str(excinfo.value)


def test_collect_speaker_labels_reads_segments_and_words() -> None:
    raw = {
        "segments": [
            {"speaker": "SPEAKER_01", "words": [{"speaker": "SPEAKER_01"}]},
            {"words": [{"speaker": "SPEAKER_02"}]},
            {"speaker": None},
        ]
    }
    assert collect_speaker_labels(raw) == ("SPEAKER_01", "SPEAKER_02")


def test_dependency_versions_has_the_expected_keys() -> None:
    versions = dependency_versions()
    for package in ("whisperx", "torch", "pyannote-audio", "python", "platform"):
        assert package in versions
