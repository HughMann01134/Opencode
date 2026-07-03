import jiwer

try:
    from whisper.normalizers import EnglishTextNormalizer # type: ignore

    _normalizer = EnglishTextNormalizer()

    def normalize_text(text: str) -> str:
        return _normalizer(text)
except ImportError:
    _fallback_pipeline = jiwer.Compose(
        [
            jiwer.ToLowerCase(),
            jiwer.RemovePunctuation(),
            jiwer.RemoveMultipleSpaces(),
            jiwer.Strip(),
        ]
    )

    def normalize_text(text: str) -> str:
        return _fallback_pipeline(text)
