"""Speech models: catalog, download with progress, loading, and NVIDIA GPU support."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths
from .log import log

ProgressFn = Callable[[int, int], None]  # (done bytes, total bytes)


@dataclass(frozen=True)
class ModelInfo:
    name: str
    title: str
    size_mb: int
    english_only: bool
    note: str
    engine: str = "whisper"     # whisper (faster-whisper) | parakeet (onnx-asr)
    repo: str = ""              # Hugging Face repo when it isn't faster-whisper's own name

    @property
    def prompts(self) -> bool:
        """Whether "Words it should know" reaches the model."""
        return self.engine == "whisper"


CATALOG: list[ModelInfo] = [
    ModelInfo("tiny.en", "Tiny", 75, True, "Fastest. Fine for short notes."),
    ModelInfo("base.en", "Base", 145, True, "Fast and decent."),
    ModelInfo("small.en", "Small", 484, True, "Runs well on most PCs."),
    ModelInfo("medium.en", "Medium", 1530, True, "More accurate, needs a fast CPU or a GPU."),
    ModelInfo("distil-large-v3.5", "Distil Large v3.5", 1515, True,
              "About as accurate as Large v3 for English, and faster."),
    ModelInfo("parakeet-tdt-0.6b-v2", "Parakeet v2", 661, True,
              "NVIDIA's English model. More accurate than Large v3, and fast without a graphics card. "
              "Ignores Words it should know.", engine="parakeet", repo="istupakov/parakeet-tdt-0.6b-v2-onnx"),
    ModelInfo("large-v3-turbo", "Large v3 Turbo", 1620, False, "Close to Large v3, much faster. Best with an NVIDIA GPU."),
    ModelInfo("tiny", "Tiny (multilingual)", 75, False, "Any language. Fastest."),
    ModelInfo("base", "Base (multilingual)", 145, False, "Any language."),
    ModelInfo("small", "Small (multilingual)", 484, False, "Any language. Runs well on most PCs."),
    ModelInfo("medium", "Medium (multilingual)", 1530, False, "Any language. More accurate."),
    ModelInfo("large-v3", "Large v3 (multilingual)", 3090, False, "Any language. The most accurate Whisper model, and the slowest."),
]
BY_NAME = {m.name: m for m in CATALOG}
# Which downloaded model to use while the chosen one downloads.
FALLBACK_ORDER = ("small.en", "base.en", "tiny.en", "large-v3-turbo", "medium.en", "distil-large-v3.5", "distil-large-v3",
                  "small", "base", "tiny", "medium", "large-v3")

LANGUAGES = {
    "auto": "Detect automatically", "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian",
    "tr": "Turkish", "ar": "Arabic", "hi": "Hindi", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
    "sv": "Swedish", "da": "Danish", "no": "Norwegian", "fi": "Finnish", "cs": "Czech", "el": "Greek",
    "he": "Hebrew", "id": "Indonesian", "vi": "Vietnamese", "th": "Thai", "ro": "Romanian", "hu": "Hungarian",
}

_FILES = {
    "whisper": ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"],
    # int8 only: a third of the float32 size, and the same accuracy in testing.
    "parakeet": ["config.json", "vocab.txt", "nemo128.onnx", "encoder-model.int8.onnx",
                 "decoder_joint-model.int8.onnx"],
}
_MAIN_FILE = {"whisper": "model.bin", "parakeet": "encoder-model.int8.onnx"}


def engine_of(name: str) -> str:
    info = BY_NAME.get(name)
    return info.engine if info else "whisper"


def repo_id(name: str) -> str:
    info = BY_NAME.get(name)
    if info and info.repo:
        return info.repo
    from faster_whisper.utils import _MODELS
    return _MODELS.get(name, name)


def cache_dir() -> str | None:
    return str(paths.MODELS) if paths.MODELS else None


def local_path(name: str) -> Path | None:
    """Folder of a fully downloaded model, or None."""
    try:
        from huggingface_hub import snapshot_download
        eng = engine_of(name)
        p = Path(snapshot_download(repo_id(name), allow_patterns=_FILES[eng], local_files_only=True,
                                   cache_dir=cache_dir()))
        return p if (p / _MAIN_FILE[eng]).exists() else None
    except Exception:
        return None


def is_downloaded(name: str) -> bool:
    return local_path(name) is not None


def downloaded() -> list[str]:
    return [m.name for m in CATALOG if is_downloaded(m.name)]


def disk_size(name: str) -> int:
    p = local_path(name)
    if not p:
        return 0
    return sum(f.stat().st_size for f in p.iterdir() if f.is_file())


def delete(name: str) -> bool:
    """Remove a downloaded model from the Hugging Face cache."""
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir(cache_dir())
        repo = repo_id(name)
        revs = [r.commit_hash for c in info.repos if c.repo_id == repo for r in c.revisions]
        if not revs:
            return False
        info.delete_revisions(*revs).execute()
        return True
    except Exception:
        log.exception("Deleting model %s failed", name)
        return False


def _repo_cache(repo: str) -> Path:
    from huggingface_hub.constants import HF_HUB_CACHE
    return Path(cache_dir() or HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))


def download(name: str, progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> Path:
    eng = engine_of(name)
    return download_files(repo_id(name), _FILES[eng], _MAIN_FILE[eng], progress, cancel)


def download_files(repo: str, patterns: list[str], main_file: str, progress: ProgressFn | None = None,
                   cancel: threading.Event | None = None, revision: str | None = None) -> Path:
    """Download matching files of a Hugging Face repo, one by one. Progress
    comes from watching the cache's blob folder, which also counts partial
    files, so it moves smoothly inside a 1.5 GB file. Cancel takes effect
    between files; a partial file resumes on the next attempt."""
    import fnmatch
    from huggingface_hub import HfApi, hf_hub_download
    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    wanted = [s for s in info.siblings if any(fnmatch.fnmatch(s.rfilename, p) for p in patterns)]
    total = sum(s.size or 0 for s in wanted) or 1
    blobs = _repo_cache(repo) / "blobs"
    stop = threading.Event()

    def watch():
        while not stop.wait(0.25):
            try:
                done = sum(f.stat().st_size for f in blobs.iterdir()) if blobs.exists() else 0
            except OSError:
                continue
            if progress:
                progress(min(done, total), total)

    watcher = threading.Thread(target=watch, daemon=True, name="model-progress")
    watcher.start()
    path = None
    try:
        for s in sorted(wanted, key=lambda s: s.size or 0):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Download cancelled")
            path = Path(hf_hub_download(repo, s.rfilename, cache_dir=cache_dir(), revision=info.sha)).parent
        # The model file is the last and largest, so the loop's check can't
        # cover it: a cancel during it must still count as cancelled.
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Download cancelled")
    finally:
        stop.set()
    if path is None or not (path / main_file).exists():
        raise RuntimeError(f"{repo} downloaded incompletely")
    if progress:
        progress(total, total)
    return path


# ------------------------------------------------------------------ GPU

# ctranslate2 4.8 ships cuDNN 9 but needs cuBLAS 12 from NVIDIA. Pinned to the
# version tested with it; the wheel is fetched from PyPI and checked by SHA-256.
CUBLAS_PKG = "nvidia-cublas-cu12"
CUBLAS_VERSION = "12.9.2.10"
CUBLAS_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll")
_gpu_dll_handle = None


def gpu_libs_present() -> bool:
    return all((paths.CUDA_DIR / d).exists() for d in CUBLAS_DLLS)


def enable_gpu_libs() -> None:
    global _gpu_dll_handle
    if gpu_libs_present() and _gpu_dll_handle is None:
        _gpu_dll_handle = os.add_dll_directory(str(paths.CUDA_DIR))
        os.environ["PATH"] = str(paths.CUDA_DIR) + os.pathsep + os.environ.get("PATH", "")


def cuda_devices() -> int:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def gpu_name() -> str:
    """Name of the first NVIDIA GPU via NVML, or ''. Works without cuBLAS."""
    try:
        nvml = ctypes.WinDLL(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvml.dll"))
    except OSError:
        return ""
    try:
        if nvml.nvmlInit_v2() != 0:
            return ""
        handle = ctypes.c_void_p()
        if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
            return ""
        buf = ctypes.create_string_buffer(96)
        if nvml.nvmlDeviceGetName(handle, buf, 96) != 0:
            return ""
        return buf.value.decode(errors="replace")
    except Exception:
        return ""
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception:
            pass


def gpu_download_size() -> int:
    return 553_162_896


def download_gpu_libs(progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> None:
    meta_url = f"https://pypi.org/pypi/{CUBLAS_PKG}/{CUBLAS_VERSION}/json"
    with urllib.request.urlopen(meta_url, timeout=30) as r:
        meta = json.load(r)
    files = [u for u in meta["urls"] if u["filename"].endswith("win_amd64.whl")]
    if not files:
        raise RuntimeError("No Windows build of cuBLAS found on PyPI")
    f = files[0]
    total, want_sha = f["size"], f["digests"]["sha256"]
    paths.CUDA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = paths.CUDA_DIR / (f["filename"] + ".part")
    sha = hashlib.sha256()
    done = 0
    req = urllib.request.Request(f["url"], headers={"User-Agent": "FreeDictate"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Download cancelled")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if sha.hexdigest() != want_sha:
            raise RuntimeError("Downloaded file failed its checksum. Try again.")
        with zipfile.ZipFile(tmp) as z:
            for info in z.infolist():
                base = info.filename.rsplit("/", 1)[-1]
                if base in CUBLAS_DLLS:
                    with z.open(info) as src, open(paths.CUDA_DIR / base, "wb") as dst:
                        while chunk := src.read(1 << 20):
                            dst.write(chunk)
    finally:
        tmp.unlink(missing_ok=True)
    if not gpu_libs_present():
        raise RuntimeError("cuBLAS libraries missing from the download")


def remove_gpu_libs() -> None:
    for d in CUBLAS_DLLS:
        (paths.CUDA_DIR / d).unlink(missing_ok=True)


def resolve_device(device: str, compute_type: str) -> tuple[str, str]:
    """Turn the auto settings into a concrete (device, compute_type)."""
    use_cuda = device == "cuda" or (device == "auto" and gpu_libs_present() and cuda_devices() > 0)
    if use_cuda:
        enable_gpu_libs()
        return "cuda", ("float16" if compute_type == "auto" else compute_type)
    return "cpu", ("int8" if compute_type in ("auto", "float16", "int8_float16") else compute_type)


def free_memory() -> None:
    """Release GPU/CPU memory held by an unloaded model.

    Deleting the Whisper object drops the reference, but CUDA blocks can
    linger until the garbage collector runs and the allocator cache is
    flushed. Best effort: never raises. The working-set trim on top hands the
    pages the process is no longer using straight back to Windows, instead of
    waiting for the memory manager to age them out."""
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    if os.name == "nt":
        try:
            psapi = ctypes.WinDLL("psapi")
            psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
            psapi.EmptyWorkingSet.restype = ctypes.c_int
            psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
        except Exception:
            pass


class _Segment:
    def __init__(self, text: str):
        self.text = text


class ParakeetModel:
    """onnx-asr Parakeet behind faster-whisper's transcribe() shape, so the
    engine decodes every model the same way. Runs on the processor: int8 on
    16 threads decodes a 10 s take in about half a second (measured)."""

    CHUNK_S = 25   # longer stretches lose words (measured: 8% dropped on a 4 min take)

    def __init__(self, path: Path, cpu_threads: int = 0):
        import onnx_asr
        import onnxruntime as rt
        opts = rt.SessionOptions()
        if cpu_threads:
            opts.intra_op_num_threads = cpu_threads
        self._m = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", str(path), quantization="int8",
                                      providers=["CPUExecutionProvider"], sess_options=opts)

    def _chunks(self, audio, vad: bool):
        from . import audio as audio_mod
        rate = audio_mod.RATE
        if len(audio) <= self.CHUNK_S * rate and not vad:
            return [audio]
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        spans = get_speech_timestamps(audio, VadOptions(max_speech_duration_s=self.CHUNK_S,
                                                        min_silence_duration_ms=400, speech_pad_ms=200))
        if not spans:
            return [] if vad else [audio]
        return [audio[s["start"]:s["end"]] for s in spans]

    def transcribe(self, audio, vad_filter: bool = True, **_ignored):
        chunks = self._chunks(audio, vad_filter)
        texts = self._m.recognize(chunks, sample_rate=16000) if chunks else []
        return iter([_Segment(" ".join(t.strip() for t in texts if t.strip()))]), None


def load(name: str, device: str, compute_type: str, cpu_threads: int = 0):
    """Load a model and run a real decode, so a broken dependency fails here
    and not silently on every dictation."""
    import numpy as np
    if engine_of(name) == "parakeet":
        path = local_path(name)
        if path is None:
            raise RuntimeError(f"{name} isn't downloaded")
        log.info("Loading %s on cpu (int8)", name)
        m = ParakeetModel(path, cpu_threads)
        list(m.transcribe(np.zeros(16000, dtype=np.float32), vad_filter=False)[0])
        return m, "cpu", "int8"
    from faster_whisper import WhisperModel
    path = local_path(name)
    dev, ct = resolve_device(device, compute_type)
    log.info("Loading %s on %s (%s)", name, dev, ct)
    try:
        m = WhisperModel(str(path) if path else name, device=dev, compute_type=ct,
                         cpu_threads=cpu_threads, download_root=cache_dir())
        list(m.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1, language="en")[0])
    except Exception:
        if dev != "cuda":
            raise
        log.exception("GPU load failed; falling back to the CPU")
        dev, ct = "cpu", "int8"
        m = WhisperModel(str(path) if path else name, device=dev, compute_type=ct,
                         cpu_threads=cpu_threads, download_root=cache_dir())
    return m, dev, ct
