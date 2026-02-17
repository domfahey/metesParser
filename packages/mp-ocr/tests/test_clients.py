"""Verify LLM client protocol and cache are importable."""


def test_base_client_protocol():
    from mp_ocr import BaseLLMClient

    assert hasattr(BaseLLMClient, "generate_text")


def test_llm_client_error():
    from mp_ocr import LLMClientError

    assert issubclass(LLMClientError, RuntimeError)


def test_cached_client_importable():
    from mp_ocr import CachedLLMClient

    assert CachedLLMClient is not None
