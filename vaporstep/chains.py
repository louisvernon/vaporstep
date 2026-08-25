from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .domain import GameNote, ImplicitChain, NoteKind, SustainSource


MAX_CHAIN_GAP_BEATS = 2.0
MIN_CHAIN_NOTES = 3
HOLD_OCCUPANCY_GRACE_SECONDS = 0.50


@dataclass(frozen=True)
class _Candidate:
    kind: NoteKind
    lanes: tuple[int, ...]
    note_indices: tuple[int, ...]
    start_time: float
    end_time: float
    start_beat: float
    end_beat: float


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return a_start <= b_end + 1e-9 and b_start <= a_end + 1e-9


def _candidate_runs(notes: list[GameNote]) -> list[_Candidate]:
    groups: dict[tuple[NoteKind, tuple[int, ...]], list[int]] = {}
    for index, note in enumerate(notes):
        if note.end_time is not None or note.beat is None:
            continue
        groups.setdefault((note.kind, note.lanes), []).append(index)

    result: list[_Candidate] = []
    for (kind, lanes), indices in groups.items():
        indices.sort(key=lambda i: (float(notes[i].beat or 0.0), notes[i].time))
        run: list[int] = []
        previous_beat: float | None = None

        def flush() -> None:
            nonlocal run
            if len(run) < MIN_CHAIN_NOTES:
                run = []
                return
            first = notes[run[0]]
            last = notes[run[-1]]
            assert first.beat is not None and last.beat is not None
            result.append(
                _Candidate(
                    kind=kind,
                    lanes=lanes,
                    note_indices=tuple(run),
                    start_time=first.time,
                    end_time=last.time,
                    start_beat=float(first.beat),
                    end_beat=float(last.beat),
                )
            )
            run = []

        for index in indices:
            beat = float(notes[index].beat)
            if previous_beat is not None and beat - previous_beat > MAX_CHAIN_GAP_BEATS + 1e-9:
                flush()
            run.append(index)
            previous_beat = beat
        flush()

    result.sort(key=lambda c: (c.start_time, -len(c.note_indices), c.kind.value, c.lanes))
    return result


def _candidate_is_playable(
    candidate: _Candidate,
    accepted: list[_Candidate],
    notes: list[GameNote],
) -> bool:
    kind = candidate.kind

    event_times: set[float] = {candidate.start_time, candidate.end_time}
    for other in accepted:
        if other.kind == kind and _overlaps(
            candidate.start_time, candidate.end_time, other.start_time, other.end_time
        ):
            event_times.update((max(candidate.start_time, other.start_time), min(candidate.end_time, other.end_time)))
    for note in notes:
        if note.kind != kind:
            continue
        note_end = note.end_time if note.end_time is not None else note.time
        if _overlaps(candidate.start_time, candidate.end_time, note.time, note_end):
            event_times.add(max(candidate.start_time, note.time))
            event_times.add(min(candidate.end_time, note_end))
        if candidate.start_time - 1e-9 <= note.time <= candidate.end_time + 1e-9:
            event_times.add(note.time)

    for t in sorted(event_times):
        occupied = set(candidate.lanes)

        for other in accepted:
            if other.kind == kind and other.start_time - 1e-9 <= t <= other.end_time + 1e-9:
                occupied.update(other.lanes)

        for note in notes:
            if note.kind != kind:
                continue
            if note.end_time is not None and note.time - 1e-9 <= t <= note.end_time + 1e-9:
                occupied.update(note.lanes)
            elif abs(note.time - t) <= 1e-9:
                occupied.update(note.lanes)

        if len(occupied) > 2:
            return False

    return True


def assign_implicit_chains(notes: Iterable[GameNote]) -> tuple[ImplicitChain, ...]:
    note_list = list(notes)
    for note in note_list:
        note.chain_id = None
        note.chain_index = 0
        note.chain_length = 1

    accepted: list[_Candidate] = []
    used_indices: set[int] = set()
    for candidate in _candidate_runs(note_list):
        if any(index in used_indices for index in candidate.note_indices):
            continue
        if not _candidate_is_playable(candidate, accepted, note_list):
            continue
        accepted.append(candidate)
        used_indices.update(candidate.note_indices)

    chains: list[ImplicitChain] = []
    for chain_id, candidate in enumerate(accepted):
        definition = ImplicitChain(
            id=chain_id,
            kind=candidate.kind,
            lanes=candidate.lanes,
            note_indices=candidate.note_indices,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            start_beat=candidate.start_beat,
            end_beat=candidate.end_beat,
            source=SustainSource.IMPLICIT_CHAIN,
        )
        chains.append(definition)
        length = len(candidate.note_indices)
        for chain_index, note_index in enumerate(candidate.note_indices):
            note = note_list[note_index]
            note.chain_id = chain_id
            note.chain_index = chain_index
            note.chain_length = length

    return tuple(chains)


def assign_explicit_holds(
    notes: Iterable[GameNote], *, first_id: int = 0
) -> tuple[ImplicitChain, ...]:
    note_list = list(notes)
    holds: list[ImplicitChain] = []
    next_id = int(first_id)
    for index, note in enumerate(note_list):
        if note.end_time is None:
            continue
        end_beat = note.end_beat
        if note.beat is None or end_beat is None or note.end_time <= note.time:
            continue
        definition = ImplicitChain(
            id=next_id,
            kind=note.kind,
            lanes=note.lanes,
            note_indices=(index,),
            start_time=note.time,
            end_time=note.end_time,
            start_beat=float(note.beat),
            end_beat=float(end_beat),
            source=SustainSource.EXPLICIT_HOLD,
        )
        holds.append(definition)
        note.chain_id = next_id
        note.chain_index = 0
        note.chain_length = 1
        next_id += 1
    return tuple(holds)


def assign_sustains(notes: Iterable[GameNote]) -> tuple[tuple[ImplicitChain, ...], tuple[ImplicitChain, ...]]:
    note_list = list(notes)
    implicit = assign_implicit_chains(note_list)
    explicit = assign_explicit_holds(note_list, first_id=len(implicit))
    all_sustains = tuple(sorted((*implicit, *explicit), key=lambda s: (s.start_time, s.id)))
    return implicit, all_sustains
