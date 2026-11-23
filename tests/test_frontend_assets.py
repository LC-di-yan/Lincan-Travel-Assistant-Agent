from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from server.frontend_assets import frontend_assets


def test_frontend_asset_compression_preserves_bytes_and_leaves_sse_uncompressed(tmp_path):
    source = b"const flightDeck = 'static map';\n" * 12000
    (tmp_path / "index-hash.js").write_bytes(source)
    app = FastAPI()
    app.mount("/assets", frontend_assets(tmp_path))

    @app.get("/api/chat")
    def chat():
        return StreamingResponse(iter([b"event: thinking\n\n", b"event: complete\n\n"]), media_type="text/event-stream")

    with TestClient(app) as client:
        compressed = client.get("/assets/index-hash.js", headers={"Accept-Encoding": "gzip"})
        assert compressed.headers["content-encoding"] == "gzip"
        assert "Accept-Encoding" in compressed.headers["vary"]
        assert compressed.content == source
        plain = client.get("/assets/index-hash.js", headers={"Accept-Encoding": "identity"})
        assert "content-encoding" not in plain.headers
        assert "Accept-Encoding" in plain.headers["vary"]
        assert plain.content == source
        event = client.get("/api/chat", headers={"Accept-Encoding": "gzip"})
        assert "content-encoding" not in event.headers
        assert event.content == b"event: thinking\n\nevent: complete\n\n"
