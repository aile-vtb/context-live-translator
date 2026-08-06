from __future__ import annotations

import json
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .config import SESSIONS_DIR
from .models import TranscriptSegment


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def safe_language_filename(code: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", code).strip(".-")
    return value or "custom"


def rebuild_segments(events_path: Path) -> OrderedDict[str, TranscriptSegment]:
    segments: OrderedDict[str, TranscriptSegment] = OrderedDict()
    if not events_path.exists():
        return segments
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
            snapshot = payload["segment"]
            segment = TranscriptSegment.from_snapshot(snapshot)
            segments[segment.id] = segment
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return segments


class SessionWriter:
    def __init__(
        self,
        target_language_code: str,
        root: Path = SESSIONS_DIR,
        now: datetime | None = None,
    ) -> None:
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        self.directory = root / stamp
        suffix = 1
        while self.directory.exists():
            self.directory = root / f"{stamp}-{suffix:02d}"
            suffix += 1
        self.directory.mkdir(parents=True, exist_ok=False)
        self.events_path = self.directory / "events.jsonl"
        self.target_language_code = target_language_code
        self.segments: OrderedDict[str, TranscriptSegment] = OrderedDict()
        self.started_at: float | None = None

    def record(self, event_type: str, segment: TranscriptSegment) -> None:
        if self.started_at is None:
            self.started_at = segment.started_at
        self.segments[segment.id] = TranscriptSegment.from_snapshot(segment.snapshot())
        payload = {
            "event_type": event_type,
            "event_at": datetime.now().astimezone().isoformat(),
            "segment": segment.snapshot(),
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            handle.flush()
        self._write_latest_outputs()

    def record_system_event(self, event_type: str, details: dict[str, object]) -> None:
        payload = {
            "event_type": event_type,
            "event_at": datetime.now().astimezone().isoformat(),
            "details": details,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            handle.flush()

    def _write_latest_outputs(self) -> None:
        if self.started_at is None:
            return
        segments = sorted(self.segments.values(), key=lambda item: (item.started_at, item.id))
        route_ids = {segment.route_id for segment in segments}
        show_routes = len(route_ids) > 1
        self._atomic_write(
            self.directory / "source.srt",
            self._render_srt(segments, False, show_route_labels=show_routes),
        )
        target_name = f"target.{safe_language_filename(self.target_language_code)}.srt"
        self._atomic_write(
            self.directory / target_name,
            self._render_srt(segments, True, show_route_labels=show_routes),
        )
        text = "\n".join(
            (
                (f"[{segment.route_label}]\n" if show_routes else "")
                + f"{segment.source_text}\n{segment.translation}".rstrip()
            )
            for segment in segments
            if segment.source_text
        )
        self._atomic_write(self.directory / "latest.txt", text + ("\n" if text else ""))
        for route_id in sorted(route_ids):
            route_segments = [segment for segment in segments if segment.route_id == route_id]
            safe_route_id = safe_language_filename(route_id)
            self._atomic_write(
                self.directory / f"source.{safe_route_id}.srt",
                self._render_srt(route_segments, False),
            )
            self._atomic_write(
                self.directory
                / f"target.{safe_language_filename(self.target_language_code)}.{safe_route_id}.srt",
                self._render_srt(route_segments, True),
            )
            route_text = "\n".join(
                f"{segment.source_text}\n{segment.translation}".rstrip()
                for segment in route_segments
                if segment.source_text
            )
            self._atomic_write(
                self.directory / f"latest.{safe_route_id}.txt",
                route_text + ("\n" if route_text else ""),
            )

    def _render_srt(
        self,
        segments: Iterable[TranscriptSegment],
        target: bool,
        show_route_labels: bool = False,
    ) -> str:
        assert self.started_at is not None
        blocks: list[str] = []
        output_index = 1
        for segment in segments:
            text = segment.translation if target else segment.source_text
            if not text:
                continue
            if show_route_labels:
                text = f"[{segment.route_label}] {text}"
            start = segment.started_at - self.started_at
            end = max(start + 0.5, segment.ended_at - self.started_at)
            blocks.append(
                f"{output_index}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n"
            )
            output_index += 1
        return "\n".join(blocks)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
