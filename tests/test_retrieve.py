"""A4 - retrieval returns passages that resolve to the real corpus; nothing for irrelevant queries."""
from src.retrieve import Corpus


def test_chunks_resolve_and_resolution_is_never_split(system):
    corpus = system.corpus
    assert len(corpus.docs) == 29
    for c in corpus.chunks:
        assert corpus.resolve(c.chunk_id) is c
        assert c.chunk_id.split("#")[0] in corpus.docs
    for doc_id in corpus.docs:
        res = corpus.resolution_chunk(doc_id)
        assert res is not None and "1." in res.text  # whole numbered sequence kept together


def test_known_question_finds_right_article(system):
    r = system.retriever.retrieve("We get 429 too many requests errors although we have several API keys", "rate_limit", 1.0)
    assert r.hit and r.passages[0].doc_id == "DOC-API-001"
    for p in r.passages:
        assert system.corpus.resolve(p.chunk_id) is not None
        assert p.text == system.corpus.resolve(p.chunk_id).text


def test_irrelevant_query_returns_nothing(system):
    r = system.retriever.retrieve("what is the best recipe for banana bread with walnuts", None, 0.0)
    assert not r.hit and r.passages == []


def test_fixed_chunking_alternative_available(settings):
    c = Corpus.load(settings.docs_path, chunking="fixed")
    assert c.chunks and all("#part" in x.chunk_id for x in c.chunks)
