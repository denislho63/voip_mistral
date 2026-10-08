"""Unit tests for the pure functions of speech_pipeline (no API access).

These tests exercise the resampling and PCM-conversion helpers and the
custom-vocabulary loader. They never touch the Mistral API: importing
speech_pipeline works even without mistralai installed (the pipeline is
simply disabled in that case).
"""

from __future__ import annotations

import struct
import sys

sys.path.insert(0, ".")

from speech_pipeline import (
    CUSTOM_VOCABULARY,
    _convert_tts_to_pcm_s16le,
    _load_custom_vocabulary,
    _resample_pcm_s16le,
)


class TestResamplePcmS16le:
    def test_same_rate_is_passthrough(self):
        pcm = struct.pack("<4h", 0, 1000, -1000, 500)
        assert _resample_pcm_s16le(pcm, 16000, 16000) == pcm

    def test_empty_input(self):
        assert _resample_pcm_s16le(b"", 24000, 16000) == b""

    def test_odd_byte_is_dropped(self):
        out = _resample_pcm_s16le(b"\x00\x01\x02", 24000, 16000)
        assert len(out) % 2 == 0

    def test_downsample_length_and_values(self):
        pcm = struct.pack("<8h", 0, 100, 200, 300, 400, 500, 600, 700)
        out = _resample_pcm_s16le(pcm, 24000, 16000)
        samples = struct.unpack(f"<{len(out) // 2}h", out)
        assert len(samples) == 5  # int(8 * 16000/24000)
        assert samples[0] == 0
        assert samples[-1] == 700

    def test_upsample_length(self):
        pcm = struct.pack("<4h", 0, 100, 200, 300)
        out = _resample_pcm_s16le(pcm, 16000, 24000)
        samples = struct.unpack(f"<{len(out) // 2}h", out)
        assert len(samples) == 6  # int(4 * 24000/16000)
        assert samples[0] == 0
        assert samples[-1] == 300

    def test_single_sample_survives_extreme_downsample(self):
        # int(1 * 16000/24000) == 0, but the sample must not be lost
        out = _resample_pcm_s16le(struct.pack("<h", -42), 24000, 16000)
        assert struct.unpack("<h", out)[0] == -42


class TestConvertTtsToPcmS16le:
    def test_basic_conversion(self):
        raw = struct.pack("<4f", 0.0, 0.5, -0.5, 0.25)
        out = _convert_tts_to_pcm_s16le(raw, 24000, 16000)
        samples = struct.unpack(f"<{len(out) // 2}h", out)
        assert len(samples) == 2  # int(4 * 16000/24000)
        assert samples[0] == 0
        # interpolated between 0.5 and -0.5 around the middle
        assert abs(samples[1] - 8191) <= 1

    def test_clamping(self):
        raw = struct.pack("<2f", 10.0, -10.0)
        out = _convert_tts_to_pcm_s16le(raw, 24000, 16000)
        samples = struct.unpack(f"<{len(out) // 2}h", out)
        assert samples[0] == 32767
        assert all(-32768 <= s <= 32767 for s in samples)

    def test_empty(self):
        assert _convert_tts_to_pcm_s16le(b"", 24000, 16000) == b""
        assert _convert_tts_to_pcm_s16le(b"\x00", 24000, 16000) == b""


class TestCustomVocabulary:
    def test_default_is_empty(self):
        # the global custom_vocabulary.txt was removed; per-domain
        # vocabularies (detection_classification) replace it
        assert CUSTOM_VOCABULARY == []

    def test_inline_env_override(self, monkeypatch):
        monkeypatch.setenv("PHONE_STREAM_VOCABULARY", "alpha, beta ,gamma")
        assert _load_custom_vocabulary() == ["alpha", "beta", "gamma"]

    def test_file_env_override(self, tmp_path, monkeypatch):
        vocab = tmp_path / "voc.txt"
        vocab.write_text("term1\n# comment\nterm2\n\n  term3  \n")
        monkeypatch.delenv("PHONE_STREAM_VOCABULARY", raising=False)
        monkeypatch.setenv("PHONE_STREAM_VACABULARY", str(vocab))
        assert _load_custom_vocabulary() == ["term1", "term2", "term3"]

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PHONE_STREAM_VOCABULARY", raising=False)
        monkeypatch.setenv("PHONE_STREAM_VACABULARY", str(tmp_path / "nope.txt"))
        assert _load_custom_vocabulary() == []
