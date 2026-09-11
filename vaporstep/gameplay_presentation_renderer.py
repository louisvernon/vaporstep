from __future__ import annotations

import time

from . import __version__
from .domain import HitQuality, NoteKind
from .provenance import current_result_provenance, display_fingerprint, play_fingerprint
from .renderer import CYAN, DIM, HIT_BRICK_POP_SECONDS, MAGENTA
from .svg_character_orientation import Renderer as CharacterRenderer


class Renderer(CharacterRenderer):
    """Character renderer with gameplay feedback and result presentation."""

    def __init__(self, screen) -> None:
        super().__init__(screen)
        self._sustain_pop_started: dict[int, float] = {}

    def reset_game_effects(self) -> None:
        super().reset_game_effects()
        self._sustain_pop_started.clear()

    def draw(self, *args, **kwargs) -> None:
        strike_events = kwargs.get("strike_events", ())
        now = time.monotonic()
        super().draw(*args, **kwargs)
        self._draw_sustain_completion_pops(strike_events, now)

    def _draw_sustain_completion_pops(self, strike_events, now: float) -> None:
        """Reuse the normal note-head pop when a sustain tail scores successfully.

        Sustain scoring can intentionally trail the rendered song clock while a
        camera inference result is still pending. Start this purely visual effect
        when the completion event first reaches the renderer rather than aging it
        from that delayed scoring timestamp.
        """
        events = tuple(
            event
            for event in strike_events
            if getattr(event, "source", "") == "sustain_complete"
        )
        active_ids = {id(event) for event in events}
        for event_id in tuple(self._sustain_pop_started):
            if event_id not in active_ids:
                del self._sustain_pop_started[event_id]

        for event in events:
            started = self._sustain_pop_started.setdefault(id(event), now)
            age = max(0.0, now - started)
            if age > HIT_BRICK_POP_SECONDS:
                continue
            if event.kind == NoteKind.HANDS:
                self._draw_hand_hit_pop(event.lane, age, HitQuality.HIT)
            elif event.kind == NoteKind.FOOT:
                self._draw_hit_pop_bar(NoteKind.FOOT, event.lane, age, HitQuality.HIT)

    def draw_results(
        self,
        song_title: str,
        chart_label: str,
        stats,
        best_score: int,
        new_high: bool,
        failed: bool = False,
        recording_status: str = "",
    ) -> None:
        provenance = current_result_provenance()
        display_title = f"{song_title} - {provenance.artist or 'Unknown artist'}"

        display_chart = chart_label
        if provenance.chart_creator:
            old_suffix = f" · {provenance.chart_creator}"
            if display_chart.endswith(old_suffix):
                display_chart = display_chart[: -len(old_suffix)]
            display_chart = f"{display_chart} · chart by {provenance.chart_creator}"

        super().draw_results(
            display_title,
            display_chart,
            stats,
            best_score,
            new_high,
            failed=failed,
            recording_status=recording_status,
        )

        w, h = self.size
        version = self.small_font.render(f"VaporStep {__version__}", True, DIM)
        self.screen.blit(version, version.get_rect(topright=(w - 18, 18)))

        if provenance.song_chart_digest:
            song_chart = self.small_font.render(
                f"SONG / CHART  {display_fingerprint(provenance.song_chart_digest)}",
                True,
                MAGENTA,
            )
            play = self.small_font.render(
                f"PLAY  {display_fingerprint(play_fingerprint(provenance.song_chart_digest, stats))}",
                True,
                CYAN,
            )
            gap = 42
            total_width = song_chart.get_width() + gap + play.get_width()
            x = max(18, (w - total_width) // 2)
            y = h - 57
            self.screen.blit(song_chart, (x, y))
            self.screen.blit(play, (x + song_chart.get_width() + gap, y))
