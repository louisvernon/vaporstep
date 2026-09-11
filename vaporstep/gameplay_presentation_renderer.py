from __future__ import annotations

import time

import pygame

from . import __version__
from .domain import BodyState, ChainMode, ChainState, NoteKind, RuntimeChain, SustainSource
from .provenance import current_result_provenance, display_fingerprint, play_fingerprint
from .renderer import BG, CYAN, DIM, GREEN, MAGENTA, WHITE, _blend
from .svg_character_orientation import Renderer as CharacterRenderer


SUSTAIN_CHARGE_DELAY_SECONDS = 1.0
SUSTAIN_CHARGE_RAMP_SECONDS = 5.0
SUSTAIN_COMPLETION_FEEDBACK_SECONDS = 0.70
SUSTAIN_COMPLETION_RING_SECONDS = 0.42


class Renderer(CharacterRenderer):
    """Character renderer with gameplay feedback and result presentation."""

    def __init__(self, screen) -> None:
        super().__init__(screen)
        self._sustain_completion_started: dict[int, tuple[float, NoteKind, int]] = {}
        self._charge_body: BodyState | None = None

    def reset_game_effects(self) -> None:
        super().reset_game_effects()
        self._sustain_completion_started.clear()
        self._charge_body = None

    @staticmethod
    def _ordinary_strike_events(strike_events):
        """Exclude sustain completions from the generic receptor-input flash."""
        return tuple(
            event
            for event in strike_events
            if getattr(event, "source", "") != "sustain_complete"
        )

    @staticmethod
    def _nominal_sustain_charge(chain: RuntimeChain, song_time: float) -> float:
        """Return timeline charge: one quiet second, then 20% per second."""
        definition = chain.definition
        if definition.source != SustainSource.EXPLICIT_HOLD:
            return 0.0
        elapsed = float(song_time) - float(definition.start_time) - SUSTAIN_CHARGE_DELAY_SECONDS
        return max(0.0, min(1.0, elapsed / SUSTAIN_CHARGE_RAMP_SECONDS))

    @classmethod
    def _sustain_charge(
        cls,
        chain: RuntimeChain,
        song_time: float,
        *,
        occupied: bool,
    ) -> float:
        """Charge while occupied; freeze and drain it while occupancy is lost."""
        if chain.state != ChainState.ACTIVE:
            return 0.0
        if occupied:
            return cls._nominal_sustain_charge(chain, song_time)
        if chain.last_occupancy_at is None:
            return 0.0
        frozen = cls._nominal_sustain_charge(chain, chain.last_occupancy_at)
        return frozen * cls._sustain_presence(chain, song_time)

    @staticmethod
    def _chain_is_occupied(chain: RuntimeChain, body: BodyState) -> bool:
        required = set(chain.definition.lanes)
        occupied = (
            body.foot_lanes
            if chain.definition.kind == NoteKind.FOOT
            else body.hand_lanes
        )
        return required.issubset(occupied)

    def draw(self, *args, **kwargs) -> None:
        strike_events = kwargs.get("strike_events", ())
        if "strike_events" in kwargs:
            # Sustain completion has its own latched result feedback below. Do
            # not also render it as a generic receptor/input pulse.
            kwargs["strike_events"] = self._ordinary_strike_events(strike_events)

        body = kwargs.get("body")
        if body is None and args:
            body = args[0]
        self._charge_body = body if isinstance(body, BodyState) else None

        now = time.monotonic()
        try:
            super().draw(*args, **kwargs)
        finally:
            self._charge_body = None
        self._draw_sustain_completion_feedback(strike_events, now)

    def _draw_chains(
        self,
        chains: tuple[RuntimeChain, ...],
        notes,
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
        beat_pulse: float = 0.0,
        downbeat: bool = False,
    ) -> None:
        super()._draw_chains(
            chains,
            notes,
            song_time,
            song_beat,
            chain_mode,
            beat_pulse=beat_pulse,
            downbeat=downbeat,
        )
        if self._charge_body is not None:
            self._draw_sustain_charge_overlay(
                chains,
                notes,
                song_time,
                song_beat,
                chain_mode,
                beat_pulse,
                downbeat,
                self._charge_body,
            )

    def _draw_sustain_charge_overlay(
        self,
        chains: tuple[RuntimeChain, ...],
        notes,
        song_time: float,
        song_beat: float,
        chain_mode: ChainMode,
        beat_pulse: float,
        downbeat: bool,
        body: BodyState,
    ) -> None:
        """Brighten the whole hold as stored charge builds toward its tail."""
        hand_colors = self._hand_chain_colors(chains, notes)
        for chain in chains:
            definition = chain.definition
            if definition.source != SustainSource.EXPLICIT_HOLD:
                continue
            if chain.state != ChainState.ACTIVE:
                continue
            if not self._timed_is_within_lookahead(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            ):
                continue

            occupied = self._chain_is_occupied(chain, body)
            charge = self._sustain_charge(chain, song_time, occupied=occupied)
            if charge <= 0.001:
                continue

            head = self._timed_progress(
                definition.start_time,
                definition.start_beat,
                song_time,
                song_beat,
            )
            tail = self._timed_progress(
                definition.end_time,
                definition.end_beat,
                song_time,
                song_beat,
            )
            lo, hi = min(head, tail), max(head, tail)
            if hi <= 0.0:
                continue

            presence = self._sustain_presence(chain, song_time)
            if definition.kind == NoteKind.FOOT:
                self._draw_foot_sustain_charge(
                    chain,
                    lo,
                    hi,
                    head,
                    presence,
                    charge,
                )
            else:
                self._draw_hand_sustain_charge(
                    chain,
                    lo,
                    hi,
                    head,
                    presence,
                    charge,
                    hand_colors.get(definition.id, MAGENTA),
                    song_time,
                    beat_pulse,
                    downbeat,
                )

    def _draw_foot_sustain_charge(
        self,
        chain: RuntimeChain,
        lo: float,
        hi: float,
        head: float,
        presence: float,
        charge: float,
    ) -> None:
        dim_fill = _blend(BG, DIM, 0.56)
        dim_edge = _blend(DIM, WHITE, 0.10)
        base_fill = _blend(dim_fill, _blend(BG, CYAN, 0.52), presence)
        base_edge = _blend(dim_edge, _blend(CYAN, WHITE, 0.30), presence)
        fill = _blend(base_fill, WHITE, 0.42 * charge)
        edge = _blend(base_edge, WHITE, 0.82 * charge)

        for lane in chain.definition.lanes:
            left0, right0 = self._lane_bounds(NoteKind.FOOT, lane, lo)
            left1, right1 = self._lane_bounds(NoteKind.FOOT, lane, hi)
            y0 = self._field_y(NoteKind.FOOT, lo)
            y1 = self._field_y(NoteKind.FOOT, hi)
            pad0 = max(2.0, (right0 - left0) * 0.10)
            pad1 = max(2.0, (right1 - left1) * 0.10)
            polygon = [
                (int(left0 + pad0), int(y0)),
                (int(right0 - pad0), int(y0)),
                (int(right1 - pad1), int(y1)),
                (int(left1 + pad1), int(y1)),
            ]
            pygame.draw.polygon(self.screen, fill, polygon)
            pygame.draw.lines(
                self.screen,
                edge,
                True,
                polygon,
                2 + int(round(3.0 * charge)),
            )

            center0 = (left0 + right0) * 0.5
            center1 = (left1 + right1) * 0.5
            pygame.draw.line(
                self.screen,
                _blend(base_edge, WHITE, min(1.0, 0.35 + 0.65 * charge)),
                (int(center0), int(y0)),
                (int(center1), int(y1)),
                2 + int(round(2.0 * charge)),
            )

            head_p = max(0.0, min(1.0, head))
            head_left, head_right = self._lane_bounds(NoteKind.FOOT, lane, head_p)
            head_y = self._field_y(NoteKind.FOOT, head_p)
            head_pad = max(2.0, (head_right - head_left) * 0.08)
            head_thickness = max(5, int(4 + 12 * head_p)) + int(round(4.0 * charge))
            dim_head = _blend(BG, DIM, 0.72)
            base_head = _blend(dim_head, CYAN, presence)
            pygame.draw.line(
                self.screen,
                _blend(base_head, WHITE, 0.88 * charge),
                (head_left + head_pad, head_y),
                (head_right - head_pad, head_y),
                head_thickness,
            )

            left, right = self._lane_bounds(NoteKind.FOOT, lane, 1.0)
            y = self._field_y(NoteKind.FOOT, 1.0)
            cap_pad = max(2.0, (right - left) * 0.08)
            base_cap = _blend(_blend(BG, DIM, 0.72), CYAN, presence)
            cap = _blend(base_cap, WHITE, 0.92 * charge)
            pygame.draw.line(
                self.screen,
                cap,
                (left + cap_pad, y),
                (right - cap_pad, y),
                9 + int(round(6.0 * charge)),
            )
            pygame.draw.line(
                self.screen,
                WHITE,
                (left + cap_pad, y),
                (right - cap_pad, y),
                2 + int(round(2.0 * charge)),
            )

    def _draw_hand_sustain_charge(
        self,
        chain: RuntimeChain,
        lo: float,
        hi: float,
        head: float,
        presence: float,
        charge: float,
        base_color,
        song_time: float,
        beat_pulse: float,
        downbeat: bool,
    ) -> None:
        dim_color = _blend(DIM, BG, 0.25)
        active_color = _blend(base_color, WHITE, 0.25)
        normal = _blend(dim_color, active_color, presence)
        charged = _blend(normal, WHITE, 0.82 * charge)

        for lane in chain.definition.lanes:
            p0 = self._hand_target_point(lane, lo)
            p1 = self._hand_target_point(lane, hi)
            pygame.draw.line(
                self.screen,
                _blend(BG, charged, 0.58),
                p0,
                p1,
                16 + int(round(10.0 * charge)),
            )
            pygame.draw.line(
                self.screen,
                charged,
                p0,
                p1,
                6 + int(round(5.0 * charge)),
            )
            self._draw_hand_note_arc(
                lane,
                max(0.0, min(1.0, head)),
                charged,
                highlight=True,
            )

        if 0.0 <= head <= 1.0:
            self._draw_hand_note_connector(
                chain.definition.lanes,
                head,
                charged,
                song_time,
                beat_pulse,
                downbeat,
            )

    def _active_sustain_completion_feedback(self, strike_events, now: float):
        """Latch completion events so feedback outlives the short event buffer."""
        events = tuple(
            event
            for event in strike_events
            if getattr(event, "source", "") == "sustain_complete"
        )
        active_event_ids = {id(event) for event in events}
        for event in events:
            self._sustain_completion_started.setdefault(
                id(event),
                (now, event.kind, int(event.lane)),
            )

        active = []
        for event_id, (started, kind, lane) in tuple(self._sustain_completion_started.items()):
            age = max(0.0, now - started)
            if age <= SUSTAIN_COMPLETION_FEEDBACK_SECONDS:
                active.append((kind, lane, age))
            elif event_id not in active_event_ids:
                del self._sustain_completion_started[event_id]
        return tuple(active)

    def _receptor_center(self, kind: NoteKind, lane: int) -> tuple[int, int]:
        if kind == NoteKind.HANDS:
            x, y = self._hand_target_point(lane, 1.0)
            return int(x), int(y)
        left, right = self._lane_bounds(NoteKind.FOOT, lane, 1.0)
        return int((left + right) * 0.5), int(self._field_y(NoteKind.FOOT, 1.0))

    def _draw_sustain_completion_feedback(self, strike_events, now: float) -> None:
        for kind, lane, age in self._active_sustain_completion_feedback(strike_events, now):
            center = self._receptor_center(kind, lane)
            theme = MAGENTA if kind == NoteKind.HANDS else CYAN

            if age <= SUSTAIN_COMPLETION_RING_SECONDS:
                phase = age / SUSTAIN_COMPLETION_RING_SECONDS
                fade = 1.0 - phase
                radius = int(12 + 42 * phase)
                ring_color = _blend(BG, _blend(theme, WHITE, 0.72), 0.30 + 0.70 * fade)
                pygame.draw.circle(
                    self.screen,
                    ring_color,
                    center,
                    radius,
                    max(1, int(round(5.0 - 3.0 * phase))),
                )
                if phase < 0.45:
                    pygame.draw.circle(
                        self.screen,
                        WHITE,
                        center,
                        max(3, int(8 * (1.0 - phase / 0.45))),
                        1,
                    )

            text_fade = 1.0
            if age > 0.42:
                text_fade = max(
                    0.0,
                    1.0 - (age - 0.42) / max(
                        0.01,
                        SUSTAIN_COMPLETION_FEEDBACK_SECONDS - 0.42,
                    ),
                )
            ok = self.hit_font.render("OK", True, _blend(BG, GREEN, text_fade))
            self.screen.blit(ok, ok.get_rect(center=(center[0], center[1] + 31)))

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