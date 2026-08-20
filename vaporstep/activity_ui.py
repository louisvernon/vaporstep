from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math

import pygame

from .activity import ActivityStore, DAILY_ACTIVITY_GOAL, DayActivity, Profile, week_start


BG = (2, 2, 8)
CYAN = (70, 245, 255)
MAGENTA = (255, 55, 210)
PURPLE = (140, 75, 255)
WHITE = (235, 245, 255)
DIM = (70, 88, 115)
GRID = (25, 64, 88)
GREEN = (95, 255, 175)


@dataclass
class NamePrompt:
    title: str
    value: str = ""
    profile_id: int | None = None

    def handle(self, event: pygame.event.Event) -> str | None:
        if event.type != pygame.KEYDOWN:
            return None
        if event.key == pygame.K_ESCAPE:
            return "cancel"
        if event.key == pygame.K_RETURN:
            return "submit" if self.value.strip() else None
        if event.key == pygame.K_BACKSPACE:
            self.value = self.value[:-1]
            return None
        text = getattr(event, "unicode", "")
        if text and text.isprintable() and len(self.value) < 32:
            self.value += text
        return None


@dataclass
class ProfilePicker:
    index: int = 0

    def clamp(self, profiles: list[Profile]) -> None:
        self.index = max(0, min(self.index, max(0, len(profiles) - 1)))


def _format_duration(seconds: float) -> str:
    minutes = int(round(max(0.0, seconds) / 60.0))
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _record_badge(current: float, previous_best: float, *, has_history: bool) -> str:
    if not has_history or current <= previous_best:
        return ""
    return "NEW RECORD"


def _nice_axis_max(value: float) -> float:
    value = max(0.0, float(value))
    if value == 0.0:
        return 1.0
    magnitude = 10.0 ** math.floor(math.log10(value))
    scaled = value / magnitude
    for step in (1.0, 2.0, 5.0, 10.0):
        if scaled <= step:
            return step * magnitude
    return 10.0 * magnitude


def _axis_scale(metric: str, maximum: float) -> tuple[float, str]:
    if metric == "time":
        if maximum < 60.0:
            divisor, suffix = 1.0, "s"
        elif maximum < 3600.0:
            divisor, suffix = 60.0, "m"
        else:
            divisor, suffix = 3600.0, "h"
        display_max = _nice_axis_max(maximum / divisor)
        label = f"{display_max:g}{suffix}"
        return display_max * divisor, label

    axis_max = _nice_axis_max(maximum)
    label = f"{int(axis_max):,}" if axis_max >= 1.0 else f"{axis_max:g}"
    return axis_max, label


def _sum_days(days: list[DayActivity], count: int = 7) -> tuple[float, int, int, int]:
    selected = days[: max(0, min(7, count))]
    return (
        sum(day.duration_seconds for day in selected),
        sum(day.stomps for day in selected),
        sum(day.punches for day in selected),
        sum(day.songs for day in selected),
    )


def draw_profile_badge(renderer, profile: Profile | None) -> None:
    if profile is None:
        return
    w, _ = renderer.size
    label = renderer.small_font.render(f"PROFILE  {profile.name.upper()}", True, DIM)
    renderer.screen.blit(label, label.get_rect(topright=(w - 18, 12)))


def draw_name_prompt(renderer, prompt: NamePrompt) -> None:
    screen = renderer.screen
    w, h = renderer.size
    shade = pygame.Surface((w, h), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 190))
    screen.blit(shade, (0, 0))
    panel = pygame.Rect(0, 0, min(620, w - 60), 210)
    panel.center = (w // 2, h // 2)
    pygame.draw.rect(screen, BG, panel)
    pygame.draw.rect(screen, CYAN, panel, 2)
    title = renderer.big_font.render(prompt.title, True, MAGENTA)
    screen.blit(title, title.get_rect(center=(w // 2, panel.top + 48)))
    value = renderer.font.render((prompt.value or "") + "_", True, WHITE)
    screen.blit(value, value.get_rect(center=(w // 2, panel.top + 108)))
    hint = renderer.small_font.render("Type a name    Enter save    Esc cancel", True, DIM)
    screen.blit(hint, hint.get_rect(center=(w // 2, panel.bottom - 34)))


def draw_profile_picker(renderer, profiles: list[Profile], picker: ProfilePicker) -> None:
    screen = renderer.screen
    w, h = renderer.size
    shade = pygame.Surface((w, h), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 185))
    screen.blit(shade, (0, 0))
    panel_h = min(h - 80, max(280, 150 + len(profiles) * 38))
    panel = pygame.Rect(0, 0, min(620, w - 60), panel_h)
    panel.center = (w // 2, h // 2)
    pygame.draw.rect(screen, BG, panel)
    pygame.draw.rect(screen, MAGENTA, panel, 2)
    title = renderer.big_font.render("PROFILES", True, MAGENTA)
    screen.blit(title, title.get_rect(center=(w // 2, panel.top + 42)))

    picker.clamp(profiles)
    y = panel.top + 90
    for index, profile in enumerate(profiles):
        active = index == picker.index
        text = renderer.font.render(profile.name, True, WHITE if active else DIM)
        screen.blit(text, text.get_rect(center=(w // 2, y)))
        if active:
            pygame.draw.line(screen, CYAN, (w // 2 - 150, y), (w // 2 - 120, y), 2)
            pygame.draw.line(screen, MAGENTA, (w // 2 + 120, y), (w // 2 + 150, y), 2)
        y += 38

    hint = renderer.small_font.render("↑/↓ choose    Enter select    N new    R rename    Esc close", True, DIM)
    screen.blit(hint, hint.get_rect(center=(w // 2, panel.bottom - 30)))


def _draw_bars(renderer, x: int, y: int, width: int, height: int, days: list[DayActivity], metric: str) -> None:
    screen = renderer.screen
    values: list[tuple[float, float]] = []
    if metric == "time":
        values = [(day.duration_seconds, 0.0) for day in days]
    elif metric == "activity":
        values = [(float(day.stomps), float(day.punches)) for day in days]
    else:
        values = [(float(day.songs), 0.0) for day in days]
    maximum, axis_label = _axis_scale(
        metric,
        max((a + b for a, b in values), default=0.0),
    )
    tick = renderer.small_font.render(axis_label, True, DIM)
    axis_margin = max(38, tick.get_width() + 10)
    plot_x = x + axis_margin
    plot_width = max(70, width - axis_margin)
    gap = 12
    bar_w = max(8, (plot_width - gap * 6) // 7)
    baseline = y + height - 24
    graph_h = max(24, height - 42)
    top = baseline - graph_h
    screen.blit(tick, tick.get_rect(midright=(plot_x - 7, top)))
    pygame.draw.line(screen, GRID, (plot_x, top), (plot_x + plot_width, top), 1)
    pygame.draw.line(screen, GRID, (plot_x, top), (plot_x, baseline), 1)
    for index, (primary, secondary) in enumerate(values):
        left = plot_x + index * (bar_w + gap)
        primary_h = int(graph_h * primary / maximum)
        secondary_h = int(graph_h * secondary / maximum)
        if primary_h:
            pygame.draw.rect(screen, CYAN, (left, baseline - primary_h, bar_w, primary_h))
        if secondary_h:
            pygame.draw.rect(
                screen,
                MAGENTA,
                (left, baseline - primary_h - secondary_h, bar_w, secondary_h),
            )
        day_label = renderer.small_font.render(days[index].day.strftime("%a")[0], True, DIM)
        screen.blit(day_label, day_label.get_rect(center=(left + bar_w // 2, baseline + 12)))
    pygame.draw.line(screen, GRID, (plot_x, baseline), (plot_x + plot_width, baseline), 1)


def draw_activity_dashboard(
    renderer,
    store: ActivityStore,
    profile: Profile,
    shown_week: date,
    *,
    today: date | None = None,
) -> None:
    today = today or date.today()
    start = week_start(shown_week)
    current = store.week(profile.id, start)
    totals = store.totals(profile.id, today=today)

    screen = renderer.screen
    screen.fill(BG)
    renderer._draw_background(0.0, 0.0, False)
    w, h = renderer.size

    title = renderer.big_font.render(f"ACTIVITY — {profile.name.upper()}", True, MAGENTA)
    screen.blit(title, (30, 24))
    week_label = f"{start.strftime('%b %d')}–{(start + timedelta(days=6)).strftime('%b %d')}"
    week = renderer.font.render(week_label.upper(), True, CYAN)
    screen.blit(week, week.get_rect(topright=(w - 34, 30)))
    nav = renderer.small_font.render("← previous week    → next week    Esc back", True, DIM)
    screen.blit(nav, nav.get_rect(topright=(w - 34, 62)))

    left_x = 38
    chart_w = int(w * 0.56)
    chart_h = max(105, int(h * 0.20))
    chart_y = 105
    for label, metric in (("TIME", "time"), ("ACTIVITY", "activity"), ("SONGS", "songs")):
        heading = renderer.small_font.render(label, True, WHITE)
        screen.blit(heading, (left_x, chart_y - 8))
        _draw_bars(renderer, left_x, chart_y + 12, chart_w, chart_h - 12, current, metric)
        if metric == "activity":
            legend = renderer.small_font.render("STOMPS  ■    PUNCHES  ■", True, DIM)
            screen.blit(legend, (left_x + 90, chart_y - 8))
        chart_y += chart_h

    compare_count = 7
    current_week = week_start(today)
    if start == current_week:
        compare_count = today.weekday() + 1
    cur_time, cur_stomps, cur_punches, cur_songs = _sum_days(current, compare_count)
    cur_actions = cur_stomps + cur_punches
    records = store.weekly_records(profile.id, before=start, day_count=compare_count)

    right_x = int(w * 0.67)
    y = 122
    heading = renderer.font.render("STREAK", True, CYAN)
    screen.blit(heading, (right_x, y))
    streak = renderer.big_font.render(f"{totals.current_streak} DAYS", True, WHITE)
    screen.blit(streak, (right_x, y + 30))
    goal = renderer.small_font.render(f"{DAILY_ACTIVITY_GOAL}+ TARGET ACTIONS / DAY", True, DIM)
    screen.blit(goal, (right_x, y + 74))

    y += 126
    period_heading = "THIS WEEK" if start == current_week else "WEEK TOTAL"
    heading = renderer.font.render(period_heading, True, CYAN)
    screen.blit(heading, (right_x, y))
    comparisons = (
        (
            "TIME",
            _format_duration(cur_time),
            _record_badge(cur_time, records.duration_seconds, has_history=records.has_history),
        ),
        (
            "ACTIONS",
            f"{cur_actions:,}",
            _record_badge(cur_actions, records.actions, has_history=records.has_history),
        ),
        (
            "SONGS",
            f"{cur_songs:,}",
            _record_badge(cur_songs, records.songs, has_history=records.has_history),
        ),
    )
    y += 38
    for label, value, delta in comparisons:
        ls = renderer.small_font.render(label, True, DIM)
        vs = renderer.font.render(value, True, WHITE)
        ds = renderer.small_font.render(delta, True, GREEN)
        screen.blit(ls, (right_x, y))
        screen.blit(vs, (right_x + 95, y - 5))
        screen.blit(ds, (right_x + 220, y))
        y += 38

    y += 20
    heading = renderer.font.render("ALL TIME", True, CYAN)
    screen.blit(heading, (right_x, y))
    all_time = (
        ("TIME", _format_duration(totals.duration_seconds)),
        ("STOMPS", f"{totals.stomps:,}"),
        ("PUNCHES", f"{totals.punches:,}"),
        ("SONGS", f"{totals.songs:,}"),
        ("BEST STREAK", f"{totals.best_streak} DAYS"),
    )
    y += 38
    for label, value in all_time:
        ls = renderer.small_font.render(label, True, DIM)
        vs = renderer.font.render(value, True, WHITE)
        screen.blit(ls, (right_x, y))
        screen.blit(vs, (right_x + 125, y - 5))
        y += 34
