import json
import socket

import httpx
from websockets.sync.client import connect

from context_live_translator.config import AppConfig
from context_live_translator.models import LanguageSpec, SegmentStatus, TranscriptSegment
from context_live_translator.overlay import (
    OverlayServer,
    overlay_style,
    segment_payload,
)


def payload(
    segment_id: str,
    started_at: float,
    translation: str,
    *,
    revision: int = 0,
    last_updated_at: float = 0,
) -> dict[str, object]:
    return {
        "id": segment_id,
        "started_at": started_at,
        "source_text": f"source {segment_id}",
        "translation": translation,
        "status": "provisional",
        "revision": revision,
        "last_updated_at": last_updated_at,
    }


def test_overlay_upserts_same_id_and_keeps_recent_order() -> None:
    server = OverlayServer(max_lines=2)
    server.publish_segment(payload("one", 1, "初譯"))
    server.publish_segment(payload("two", 2, "第二句"))
    server.publish_segment(payload("one", 1, "回修譯文"))
    snapshot = server.snapshot()
    assert [item["id"] for item in snapshot["segments"]] == ["one", "two"]
    assert snapshot["segments"][0]["translation"] == "回修譯文"
    assert snapshot["segments"][0]["update_sequence"] == 3


def test_overlay_rejects_late_provisional_after_revision() -> None:
    server = OverlayServer()
    server.publish_segment(payload("one", 1, "初譯", last_updated_at=10))
    server.publish_segment(
        payload("one", 1, "上下文修正版", revision=1, last_updated_at=20)
    )
    server.publish_segment(payload("one", 1, "遲到的初譯", last_updated_at=10))

    snapshot = server.snapshot()

    assert snapshot["sequence"] == 2
    assert snapshot["segments"][0]["translation"] == "上下文修正版"
    assert snapshot["segments"][0]["revision"] == 1


def test_old_finalization_update_does_not_displace_recent_line() -> None:
    server = OverlayServer(max_lines=2)
    server.publish_segment(payload("one", 1, "一"))
    server.publish_segment(payload("two", 2, "二"))
    server.publish_segment(payload("three", 3, "三"))
    server.publish_segment(payload("one", 1, "一（鎖定）"))
    assert [item["id"] for item in server.snapshot()["segments"]] == ["two", "three"]


def test_preview_is_removed_by_real_caption() -> None:
    server = OverlayServer(max_lines=3)
    server.publish_preview()
    server.publish_segment(payload("real", 10, "真實字幕"))
    assert [item["id"] for item in server.snapshot()["segments"]] == ["real"]


def test_segment_payload_preserves_stable_id_and_revision() -> None:
    segment = TranscriptSegment(
        "stable-id",
        1,
        2,
        "en",
        LanguageSpec("zh-TW", "繁中"),
        "raw",
        "corrected",
        "修訂譯文",
        status=SegmentStatus.PROVISIONAL,
        revision=2,
    )
    result = segment_payload(segment)
    assert result is not None
    assert result["id"] == "stable-id"
    assert result["source_text"] == "corrected"
    assert result["revision"] == 2
    assert result["route_id"] == "main"
    assert result["route_label"] == "主要音訊"


def test_overlay_http_and_websocket_snapshot() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = OverlayServer(port=port, style=overlay_style(AppConfig()))
    server.publish_segment(payload("one", 1, "你好"))
    server.start()
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/overlay", trust_env=False)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert "Context Live Translator Overlay" in response.text
        assert "new WebSocket" in response.text
        assert 'get("route")' in response.text
        assert "messageSequence < lastSequence" in response.text
        health = httpx.get(
            f"http://127.0.0.1:{port}/health", trust_env=False
        ).json()
        assert health["service"] == "context-live-translator-overlay"
        with connect(f"ws://127.0.0.1:{port}/ws/overlay") as websocket:
            message = json.loads(websocket.recv(timeout=2))
            assert message["type"] == "snapshot"
            assert message["segments"][0]["id"] == "one"
            initial_sequence = message["sequence"]
            server.publish_segment(payload("one", 1, "回修後", revision=1))
            update = json.loads(websocket.recv(timeout=2))
            assert update["type"] == "upsert"
            assert update["event_type"] == "revision"
            assert update["replace_id"] == "one"
            assert update["sequence"] > initial_sequence
            assert update["segment"]["id"] == "one"
            assert update["segment"]["translation"] == "回修後"
    finally:
        server.stop()


def test_clear_keeps_style_but_removes_segments() -> None:
    server = OverlayServer(style={"show_source": True})
    server.publish_segment(payload("one", 1, "你好"))
    server.clear()
    assert server.snapshot() == {
        "type": "snapshot",
        "segments": [],
        "style": {"show_source": True},
        "sequence": 2,
    }
