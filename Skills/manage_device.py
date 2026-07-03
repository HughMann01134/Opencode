import torch


def detect_device(requested_device: str = "auto") -> str:
    """Resolves auto to cuda (if GPU available) or cpu. Validates explicit cuda requests."""
    if requested_device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"

    if requested_device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(
                "Explicit CUDA requested, but PyTorch cannot find an active GPU."
            )
        return "cuda"

    return "cpu"


def determine_compute_type(device: str, requested_type: str | None) -> str:
    """Determines best quantization type or validates explicitly requested types."""
    if requested_type is None:
        return "float16" if device == "cuda" else "int8"

    if device == "cuda" and requested_type == "int8":
        raise ValueError(
            "Invalid configuration: int8 quantization on sm_120 causes cuBLAS crashes. Use float16 on GPU."
        )
    if device == "cpu" and requested_type == "float16":
        raise ValueError(
            "Invalid configuration: float16 is GPU-only under CTranslate2. Use int8, int16, or float32."
        )

    return requested_type


def gpu_available() -> bool:
    """True only if PyTorch can see a usable CUDA GPU."""
    try:
        return torch.cuda.is_available() and torch.cuda.device_count() > 0
    except Exception:
        return False


def plan_device_passes(requested_device: str = "auto") -> list[tuple[str, str]]:
    """Resolve a device request into an ORDERED list of (device, compute_type)
    passes to benchmark.

        auto / both : GPU pass FIRST (if a GPU is detected) then a CPU pass, so
                      performance is captured both with the external card
                      attached and on CPU alone. CPU-only when no GPU exists.
        cuda        : GPU pass only (raises if no GPU is visible).
        cpu         : CPU pass only, even when a GPU is attached — the device is
                      forced to "cpu", so the external card does NOT need to be
                      physically disconnected to collect CPU-only numbers.

    compute_type is fixed by the safety rules above (cuda->float16, cpu->int8).
    """
    req = requested_device.lower()
    if req == "cpu":
        return [("cpu", determine_compute_type("cpu", None))]
    if req == "cuda":
        detect_device("cuda")  # raises RuntimeError if no GPU is visible
        return [("cuda", determine_compute_type("cuda", None))]
    if req in ("auto", "both"):
        passes: list[tuple[str, str]] = []
        if gpu_available():
            passes.append(("cuda", determine_compute_type("cuda", None)))
        passes.append(("cpu", determine_compute_type("cpu", None)))
        return passes
    raise ValueError(
        f"Unknown device request {requested_device!r} (use auto, both, cuda, or cpu)."
    )
