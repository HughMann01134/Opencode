import jiwer


class CorpusMetricAccumulator:
    """Accumulates edits across all utterances to calculate true corpus-level WER/CER."""

    def __init__(self):
        # Word-level edit counters
        self.word_subs = self.word_dels = self.word_ins = self.word_hits = 0
        # Character-level edit counters
        self.char_subs = self.char_dels = self.char_ins = self.char_hits = 0

    def add_utterance(self, reference: str, hypothesis: str) -> tuple[float, float]:
        """
        Scores an utterance, updates global counts, and returns per-sentence (wer, cer).
        Handles empty hypotheses gracefully (forces deletions).
        """
        # Word-level metrics
        w_err = jiwer.process_words(reference, hypothesis)
        self.word_subs += w_err.substitutions
        self.word_dels += w_err.deletions
        self.word_ins += w_err.insertions
        self.word_hits += w_err.hits

        # Character-level metrics
        c_err = jiwer.process_characters(reference, hypothesis)
        self.char_subs += c_err.substitutions
        self.char_dels += c_err.deletions
        self.char_ins += c_err.insertions
        self.char_hits += c_err.hits

        return w_err.wer, c_err.cer

    @property
    def corpus_wer(self) -> float:
        total_ref_words = self.word_subs + self.word_dels + self.word_hits
        if total_ref_words == 0:
            return 0.0
        return (self.word_subs + self.word_dels + self.word_ins) / total_ref_words

    @property
    def corpus_cer(self) -> float:
        total_ref_chars = self.char_subs + self.char_dels + self.char_hits
        if total_ref_chars == 0:
            return 0.0
        return (self.char_subs + self.char_dels + self.char_ins) / total_ref_chars
