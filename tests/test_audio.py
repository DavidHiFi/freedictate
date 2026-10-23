"""Exclusive-capture resampling (audio.py): no audio device is opened.

The recorder's callback is driven with synthetic native-rate blocks, the way
PortAudio would call it, then stopped as a take would be."""
import numpy as np
import pytest
import soxr

from freedictate import audio


def _feed(rec, rate, seconds, channels=2, block=800, signal=None):
    rec._native_rate = rate
    rec._resampler = soxr.ResampleStream(rate, audio.RATE, 1, dtype="float32", quality="HQ")
    total = int(rate * seconds)
    x = signal if signal is not None else np.random.default_rng(1).standard_normal(total).astype(np.float32) * 0.1
    for i in range(0, total, block):
        part = x[i:i + block]
        rec._exclusive_callback(np.repeat(part[:, None], channels, axis=1), len(part), None, None)
    return rec.stop()


@pytest.mark.parametrize("rate", [48000, 44100, 96000, 32000])
def test_n_seconds_in_gives_exactly_n_times_16000_samples(rate):
    data, secs = _feed(audio.Recorder(), rate, 5)
    assert len(data) == 5 * audio.RATE
    assert secs == 5.0


def test_odd_block_sizes_do_not_drift():
    # 441-frame blocks at 44.1 kHz were the worst case for per-block rounding.
    data, _ = _feed(audio.Recorder(), 44100, 3, block=441)
    assert len(data) == 3 * audio.RATE


def test_content_above_8k_is_filtered_not_aliased():
    rate, secs = 48000, 2
    t = np.arange(rate * secs) / rate
    tone = (0.5 * np.sin(2 * np.pi * 12000 * t)).astype(np.float32)   # would alias to 4 kHz
    data, _ = _feed(audio.Recorder(), rate, secs, signal=tone)
    body = data[1000:-1000]
    assert float(np.sqrt(np.mean(body * body))) < 0.005   # input RMS is 0.35


def test_in_band_tone_survives():
    rate, secs = 48000, 2
    t = np.arange(rate * secs) / rate
    tone = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    data, _ = _feed(audio.Recorder(), rate, secs, signal=tone)
    body = data[1000:-1000]
    assert abs(float(np.sqrt(np.mean(body * body))) - 0.5 / np.sqrt(2)) < 0.01


def test_exclusive_device_match_is_looked_up_once_per_mic(monkeypatch):
    """Matching the mic to its WASAPI device re-listed every audio device on
    each take start: 90-170 ms before recording began (measured 2026-10-24)."""
    calls = []
    monkeypatch.setattr(audio, "_find_wasapi_native", lambda name: calls.append(name) or (7, 48000.0, 2))
    audio.forget_device_matches()
    assert audio._wasapi_native("") == (7, 48000.0, 2)
    assert audio._wasapi_native("") == (7, 48000.0, 2)
    assert calls == [""]
    audio.forget_device_matches()
    audio._wasapi_native("")
    assert calls == ["", ""]


def test_a_failed_exclusive_open_forgets_the_match(monkeypatch):
    monkeypatch.setattr(audio, "_find_wasapi_native", lambda name: (7, 48000.0, 2))
    audio.forget_device_matches()

    class Refused:
        def __init__(self, *a, **k):
            raise RuntimeError("device unavailable")

    class FakeSd:
        InputStream = Refused

        @staticmethod
        def WasapiSettings(exclusive):
            return object()
    monkeypatch.setattr(audio, "_sd", lambda: FakeSd)
    with pytest.raises(RuntimeError):
        audio.Recorder().start("", exclusive=True)
    assert "" not in audio._native_matches
