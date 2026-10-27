# Retrieval experiment (development tickets, answerable only)

Generated 2026-10-27T13:14:34+00:00 by `python -m evaluation.retrieval_experiment`.

| chunking | backend | chunks | intent prior | top-1 | hit@3 | full resolution passed to generator |
|---|---|---|---|---|---|---|
| section | tfidf | 116 | 0.0 | 89.1% | 96.4% | 100.0% |
| section | tfidf | 116 | 0.35 | 97.2% | 100.0% | 100.0% |
| section | chroma-minilm | - | - | unavailable: ModuleNotFoundError: No module named 'chromadb' | | |
| fixed | tfidf | 58 | 0.0 | 88.0% | 95.8% | 5.9% |
| fixed | tfidf | 58 | 0.35 | 98.3% | 100.0% | 9.5% |
| fixed | chroma-minilm | - | - | unavailable: ModuleNotFoundError: No module named 'chromadb' | | |

Note: the intent prior here uses the true intent label (an upper bound); in the running system it uses the predicted intent weighted by its confidence.
