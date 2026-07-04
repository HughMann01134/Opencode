import pytest
from unittest.mock import patch
from Skills.manage_device import determine_compute_type, plan_device_passes
from Skills.normalize_text import normalize_text

def test_manage_device_illegal_combos():
    # int8 + cuda should raise ValueError
    with pytest.raises(ValueError, match="Invalid configuration: int8 quantization"):
        determine_compute_type("cuda", "int8")

    # float16 + cpu should raise ValueError
    with pytest.raises(ValueError, match="Invalid configuration: float16 is GPU-only"):
        determine_compute_type("cpu", "float16")

    # Valid combos should return the requested type or resolve default
    assert determine_compute_type("cuda", "float16") == "float16"
    assert determine_compute_type("cpu", "int8") == "int8"
    assert determine_compute_type("cuda", None) == "float16"
    assert determine_compute_type("cpu", None) == "int8"

@patch("Skills.manage_device.gpu_available")
@patch("Skills.manage_device.torch.cuda.is_available")
def test_plan_passes_cuda_unavailable(mock_is_available, mock_gpu_available):
    mock_is_available.return_value = False
    mock_gpu_available.return_value = False

    # auto/both should return only cpu pass
    passes = plan_device_passes("auto")
    assert passes == [("cpu", "int8")]

    passes_both = plan_device_passes("both")
    assert passes_both == [("cpu", "int8")]

@patch("Skills.manage_device.gpu_available")
@patch("Skills.manage_device.torch.cuda.is_available")
def test_plan_passes_cuda_available(mock_is_available, mock_gpu_available):
    mock_is_available.return_value = True
    mock_gpu_available.return_value = True

    # auto/both should return cuda pass first then cpu pass
    passes = plan_device_passes("auto")
    assert passes == [("cuda", "float16"), ("cpu", "int8")]

    passes_both = plan_device_passes("both")
    assert passes_both == [("cuda", "float16"), ("cpu", "int8")]

def test_normalize_text_collapse():
    # Casing and punctuation collapse to equal strings
    text1 = "Hello, World!"
    text2 = "hello world"
    assert normalize_text(text1) == normalize_text(text2)

    text3 = "  This is a   test...  "
    text4 = "this is a test"
    assert normalize_text(text3) == normalize_text(text4)
