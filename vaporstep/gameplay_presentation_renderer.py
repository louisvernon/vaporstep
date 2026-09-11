from __future__ import annotations

import time

from . import __version__
from .domain import NoteKind
from .provenance import current_result_provenance, display_fingerprint, play_fingerprint
from .renderer import CYAN, DIM, MAGENTA, WHITE, _blend
from .svg_character_orientation import Renderer as CharacterRenderer


SUSTAIN_COMPLETION_FLASH_SECONDS = 0.30


class Renderer(CharacterRenderer):
    """Character renderer with gameplay feedback and result presentation."""

    def __init__(self, screen) -> None:
        super().__init__(screen)
        self._sustain_flash_started: dict[int, float] = {}

    def reset_game_effects(self) -> None:
        super().reset_game_effects()
        self._sustain_flash_started.clear()

    @staticmethod
    def _ordinary_strike_events(strike_events):
        """Exclude sustain completions from the generic receptor-input flash."""
        return tuple(
            event
            for event in strike_events
            if getattr(event, "source", "") != "sustain_complete"
        )

    def draw(self, *args, **kwargs) -> None:
        strike_events = kwargs.get("strike_events", ())
        if "strike_events" in kwargs:
            # Sustain completion has its own note-shaped confirmation below. Do
            # not also render it as the generic receptor/input pulse, which was
            # visually ambiguous in play testing.
            kwargs["strike_events"] = self._ordinary_strike_events(strike_events)

        now = time.monotonic()
        super().draw(*args, **kwargs)
        self._draw_sustain_completion_flashes(strike_events, now)

    def _draw_sustain_completion_flashes(self, strike_events, now: float) -> None:
        """Flash the actual note-head shape when a sustain tail scores.

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
        for event_id in tuple(self._sustain_flash_started):
            if event_id not in active_ids:
                del self._sustain_flash_started[event_id]

        for event in events:
            started = self._sustain_flash_started.setdefault(id(event), now)
            age = max(0.0, now - started)
            if age > SUSTAIN_COMPLETION_FLASH_SECONDS:
                continue

            phase = min(1.0, age / SUSTAIN_COMPLETION_FLASH_SECONDS)
            theme = MAGENTA if event.kind == NoteKind.HANDS else CYAN
            color = _blend(WHITE, theme, phase ** 0.70)

            # Draw the same shape as a real note head, directly at the receptor.
            # This reads as the hold itself completing rather than as unrelated
            # receptor activity.
            if event.kind == NoteKind.HANDS:
                self._draw_hand_note_arc(event.lane, 1.0, color, highlight=True)
            elif event.kind == NoteKind.FOOT:
                self._draw_note_bar(NoteKind.FOOT, event.lane, 1.0, color, hit=True)

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
