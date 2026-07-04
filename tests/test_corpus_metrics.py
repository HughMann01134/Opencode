
import pytest
from Skills.compute_wer_cer import CorpusMetricAccumulator

def test_corpus_wer_cer_basic():
    accumulator = CorpusMetricAccumulator()

    # Utterance 1
    ref1 = "hello world"
    hyp1 = "hello worl" # 1 substitution (d)
    accumulator.add_utterance(ref1, hyp1)

    # Utterance 2
    ref2 = "this is a test"
    hyp2 = "this is test" # 1 deletion (a)
    accumulator.add_utterance(ref2, hyp2)

    # Utterance 3
    ref3 = "another example"
    hyp3 = "anothr example" # 1 substitution (e)
    accumulator.add_utterance(ref3, hyp3)

    # Total words: 2 + 4 + 2 = 8
    # Total word errors: 1 (sub) + 1 (del) + 1 (sub) = 3
    # Expected WER = 3 / 8 = 0.375

    # Total chars: 11 + 14 + 15 = 40
    # Total char errors: approx 1 (l->space) + 1 (e->space) + 1 (h->r) = 3
    # This is a simplification; jiwer calculates exact character distances.
    # The key is that it's corpus-level. Let's use simpler char counts.
    # ref1 chars: 'h','e','l','l','o',' ','w','o','r','l','d' (11)
    # hyp1 chars: 'h','e','l','l','o',' ','w','o','r','l'    (10)
    # 1 deletion.
    # ref2 chars: 't','h','i','s',' ','i','s',' ','a',' ','t','e','s','t' (14)
    # hyp2 chars: 't','h','i','s',' ','i','s',' ','t','e','s','t'       (12)
    # 1 deletion.
    # ref3 chars: 'a','n','o','t','h','e','r',' ','e','x','a','m','p','l','e' (15)
    # hyp3 chars: 'a','n','o','t','h','r',' ','e','x','a','m','p','l','e'    (14)
    # 1 substitution.

    # Total reference words: 11
    # Total errors (sub+del+ins)
    # For WER:
    #   ref1: hello world (2 words)
    #   hyp1: hello worl (2 words)
    #   diff: {hello:0} {world:1} -> {worl:1} = 1 sub, 0 del, 0 ins (jiwer counts differently, often as del+ins)
    # jiwer process_words for "hello world", "hello worl":
    #   hits=1, subs=1, dels=0, ins=0. Ref words = 2. WER = (1+0+0)/2 = 0.5
    # jiwer process_words for "this is a test", "this is test":
    #   hits=2, subs=0, dels=1, ins=0. Ref words = 4. WER = (0+1+0)/4 = 0.25
    # jiwer process_words for "another example", "anothr example":
    #   hits=1, subs=1, dels=0, ins=0. Ref words = 2. WER = (1+0+0)/2 = 0.5

    # Let's adjust expected values based on jiwer's behavior and the blueprint's "true corpus-level aggregates"
    # Blueprint: "edits divided by total reference lengths"

    # For words:
    # ref1: 2 words, hypothesis has 1 sub (d vs empty implies del+ins or 1 sub if len matches)
    #       jiwer.process_words("hello world", "hello worl") -> subs=1, dels=0, ins=0, hits=1. Ref words = 2
    # ref2: 4 words, hypothesis has 1 del ("a")
    #       jiwer.process_words("this is a test", "this is test") -> subs=0, dels=1, ins=0, hits=3. Ref words = 4
    # ref3: 2 words, hypothesis has 1 sub ('e' vs empty)
    #       jiwer.process_words("another example", "anothr example") -> subs=1, dels=0, ins=0, hits=1. Ref words = 2

    # Total for corpus_wer:
    # Total substitutions = 1 + 0 + 1 = 2
    # Total deletions = 0 + 1 + 0 = 1
    # Total insertions = 0 + 0 + 0 = 0
    # Total hits = 1 + 3 + 1 = 5
    # Total reference words = total_subs + total_dels + total_hits = 2 + 1 + 5 = 8
    # Corpus WER = (total_subs + total_dels + total_ins) / total_reference_words = (2 + 1 + 0) / 8 = 3 / 8 = 0.375

    # For chars (using the simplified deletion/substitution logic above, but jiwer will be more precise):
    # Total reference characters are calculated based on lengths of reference strings
    # "hello world" (11)
    # "this is a test" (14)
    # "another example" (15)
    # Total reference chars = 11 + 14 + 15 = 40

    # Let's manually run jiwer for characters for more precision for expected CER
    # jiwer.process_characters("hello world", "hello worl") -> hits=10, subs=0, dels=1, ins=0. Ref chars = 11. CER = 1/11
    # jiwer.process_characters("this is a test", "this is test") -> hits=12, subs=0, dels=2, ins=0. Ref chars = 14. CER = 2/14
    # jiwer.process_characters("another example", "anothr example") -> hits=14, subs=1, dels=0, ins=0. Ref chars = 15. CER = 1/15

    # Total for corpus_cer:
    # Total char subs = 0 + 0 + 1 = 1
    # Total char dels = 1 + 2 + 0 = 3
    # Total char ins = 0 + 0 + 0 = 0
    # Total char hits = 10 + 12 + 14 = 36
    # Total reference chars = total_subs + total_dels + total_hits = 1 + 3 + 36 = 40
    # Corpus CER = (total_char_subs + total_char_dels + total_char_ins) / total_reference_chars = (1 + 3 + 0) / 40 = 4 / 40 = 0.1

    assert accumulator.corpus_wer == pytest.approx(0.375)
    assert accumulator.corpus_cer == pytest.approx(0.1)

def test_corpus_wer_empty_hypothesis():
    accumulator = CorpusMetricAccumulator()
    ref = "hello world"
    hyp = ""
    accumulator.add_utterance(ref, hyp)

    # Reference words: 2
    # Hypothesis words: 0
    # jiwer will likely count 2 deletions for words.
    # Total reference words = 2
    # Total deletions = 2
    # Corpus WER = 2/2 = 1.0

    # Reference chars: 11
    # Hypothesis chars: 0
    # jiwer will count 11 deletions for chars.
    # Total reference chars = 11
    # Total deletions = 11
    # Corpus CER = 11/11 = 1.0

    assert accumulator.corpus_wer == pytest.approx(1.0)
    assert accumulator.corpus_cer == pytest.approx(1.0)

def test_corpus_wer_empty_reference():
    accumulator = CorpusMetricAccumulator()
    ref = ""
    hyp = "hello world"
    accumulator.add_utterance(ref, hyp)

    # Reference words: 0
    # Hypothesis words: 2
    # jiwer will count 2 insertions.
    # Total reference words = 0 (this is the edge case the blueprint mentions: "if total_ref_words == 0: return 0.0")
    # Total insertions = 2
    # Corpus WER = 0.0 (as per blueprint logic)

    # Reference chars: 0
    # Hypothesis chars: 11
    # jiwer will count 11 insertions.
    # Total reference chars = 0
    # Corpus CER = 0.0 (as per blueprint logic)

    assert accumulator.corpus_wer == pytest.approx(0.0)
    assert accumulator.corpus_cer == pytest.approx(0.0)

def test_corpus_metrics_with_failure():
    accumulator = CorpusMetricAccumulator()

    # Successful utterance
    ref1 = "hello world"
    hyp1 = "hello world"
    accumulator.add_utterance(ref1, hyp1)

    # Failed utterance scored as empty hypothesis
    ref2 = "another test"
    hyp2 = ""
    accumulator.add_utterance(ref2, hyp2)

    # Successful: ref words = 2, char len = 11 (0 errors)
    # Failed (empty hyp): ref words = 2, char len = 12 (all errors as deletion)
    # Total ref words = 4, Total word errors = 2
    # Total ref chars = 23, Total char errors = 12

    assert accumulator.corpus_wer == pytest.approx(2 / 4)
    assert accumulator.corpus_cer == pytest.approx(12 / 23)
