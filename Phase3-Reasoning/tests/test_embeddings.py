from pulse.analysis.embeddings import embed_texts


class FakeEmbeddingClient:
    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t)), 0.0] for t in texts]


def test_embed_texts_preserves_order_and_count():
    client = FakeEmbeddingClient()
    vectors = embed_texts(["a", "bb", "ccc"], client=client)
    assert len(vectors) == 3
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0
    assert vectors[2][0] == 3.0


def test_embed_texts_batches():
    client = FakeEmbeddingClient()
    texts = [f"text{i}" for i in range(10)]
    embed_texts(texts, client=client, batch_size=3)
    assert len(client.calls) == 4  # 3+3+3+1
    assert sum(len(c) for c in client.calls) == 10


def test_embed_texts_empty_input():
    client = FakeEmbeddingClient()
    assert embed_texts([], client=client) == []
    assert client.calls == []
