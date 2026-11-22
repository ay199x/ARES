# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's film buttons: Step plays the whole film of the instruction it runs, One step
forward only its first step and then one step at a time; One step back, Play and Pause, Skip to
end; which of them work in each state, and their keys."""

import pytest
from test_gui_run import loaded, run_until, slow, type_line
from test_gui_xray import (FOREVER, LARGEST, MULTIPLE, PROGRAM, READ, TWO_MOVES, at,
                           canvas_state, connected, opened, panel, pause_shows, sentence, steps,
                           text_of, to_end)

from conftest import press_key

from ares.gui import icons
from ares.gui.tools import xray as tool
from ares.gui.tools.xray import STEPS, WHOLE, button_states, step_end
from ares.runner import State

NAMES = ("pause", "back", "forward", "skip", "step", "backstep")


def on(window):
    """Which buttons are on: the film's Play or Pause, One step back, One step forward and Skip
    to end, and the toolbar's Step and Backstep."""
    buttons = (window.pause_button, window.back_button, window.one_button, window.skip_button,
               window.tool_buttons["step"], window.tool_buttons["backstep"])
    return {name for name, button in zip(NAMES, buttons) if button.instate(["!disabled"])}


def tips(window):
    return [window.tip_text(f"strip:{index}") for index in range(len(window.strip))]


def shown(window):
    """What a canvas shows: every item that is not hidden (test_gui_xray.canvas_state()); an
    item hidden keeps the place and colour it had when a later step was drawn."""
    return [entry for entry in canvas_state(window) if ("state", "hidden") not in entry[2]]


def forward_to(window, number):
    """One step forward, number + 1 times from no film: the film waits at the end of step
    number."""
    for _ in range(number + 1):
        window.one_button.invoke()
        to_end(window)


# (mode, ended, playing, first step, the program runs, Step possible, Backstep possible): the
# buttons that are on.
EVERYTHING_ON = {"pause", "back", "forward", "skip", "backstep"}
TABLE = [
    # No film was begun: after Assemble, Backstep or Reset, or a Step without Animate each step.
    ((None, True, False, True, False, True, False), {"forward", "step"}),
    ((None, True, False, True, False, True, True), {"forward", "step", "backstep"}),
    ((None, True, False, True, False, False, True), {"backstep"}),     # the program has ended
    # A film begun by Step: playing, paused, ended.
    ((WHOLE, False, True, True, False, True, True), {"pause", "skip", "backstep"}),
    ((WHOLE, False, False, False, False, True, True), {"pause", "skip", "backstep"}),
    ((WHOLE, True, False, False, False, True, True), {"forward", "step", "backstep"}),
    # A film begun by One step forward: at its first step (or in it), at a later step, playing
    # after Play, paused within a step, ended, ended with the program.
    ((STEPS, False, False, True, False, True, True), {"pause", "forward", "skip", "backstep"}),
    ((STEPS, False, True, True, False, True, True), {"pause", "forward", "skip", "backstep"}),
    ((STEPS, False, False, False, False, True, True), EVERYTHING_ON),
    ((STEPS, False, True, False, False, True, True), EVERYTHING_ON),
    ((STEPS, True, False, False, False, True, True), {"back", "forward", "step", "backstep"}),
    ((STEPS, True, False, False, False, False, True), {"back", "backstep"}),
    # The program runs (Go): none of the film's buttons.
    ((None, True, False, True, True, False, False), set()),
    ((STEPS, False, False, False, True, False, False), set()),
]


@pytest.mark.parametrize("state, wanted", TABLE)
def test_which_buttons_are_on_in_each_state(state, wanted):
    states = button_states(*state)
    face = states.pop("face")
    assert set(states) == set(NAMES)
    assert {name for name, value in states.items() if value} == wanted
    assert face == ("film_pause" if state[2] else "film_play")     # Pause while it plays


def test_the_buttons_follow_the_film(app, tmp_path):
    """After Assemble; during and after a film begun by Step; during and after one begun by One
    step forward, at its first step, at a later one, in the middle after Play and Pause; after
    a Backstep."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    assert window.mode is None and on(window) == {"forward", "step"}
    app.run("step")                             # Step: the whole film plays
    assert window.mode == WHOLE and window.player.playing
    assert on(window) == {"pause", "skip", "backstep"} and pause_shows(window) == "Pause"
    window.pause_button.invoke()
    assert on(window) == {"pause", "skip", "backstep"} and pause_shows(window) == "Play"
    window.pause_button.invoke()
    to_end(window)
    assert on(window) == {"forward", "step", "backstep"} and pause_shows(window) == "Play"
    window.one_button.invoke()                  # the next instruction, its first step
    assert len(app.machine.history) == 2 and window.mode == STEPS
    assert on(window) == {"pause", "forward", "skip", "backstep"}
    to_end(window)
    first = window.film.steps[0]
    assert window.player.held and window.player.paused_at == pytest.approx(
        first.start + first.duration)
    assert on(window) == {"pause", "forward", "skip", "backstep"}  # at the first step: no back
    window.one_button.invoke()
    to_end(window)
    assert on(window) == EVERYTHING_ON and pause_shows(window) == "Play"
    window.pause_button.invoke()                # Play: on to the end
    assert window.player.playing and pause_shows(window) == "Pause"
    at(window, 0.3)
    window.pause_button.invoke()                # Pause, within a step
    assert window.player.paused_at is not None and not window.player.held
    assert on(window) == EVERYTHING_ON
    window.skip_button.invoke()
    assert on(window) == {"back", "forward", "step", "backstep"}
    assert len(app.machine.history) == 2
    app.run("backstep")
    assert window.mode is None and on(window) == {"forward", "step", "backstep"}


def test_while_the_program_runs_the_film_buttons_are_off(app, tmp_path):
    """Go at a slow speed ends a film that has not ended; each instruction shows finished."""
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    window.one_button.invoke()                  # a film step by step, not ended
    slow(app, 25)
    app.run("go")
    run_until(app, lambda: len(app.machine.history) >= 3, limit=10)
    assert app.runner.state is State.RUNNING and on(window) == set()
    assert window.mode is None and not window.player.playing
    window.one_button.invoke()
    window.back_button.invoke()
    assert app.runner.state is State.RUNNING
    app.run("pause")
    assert on(window) == {"forward", "step", "backstep"}


def test_without_animate_each_step_a_step_leaves_no_film_that_has_not_ended(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    window.animate_box.invoke()
    app.run("step")
    assert window.mode is None and on(window) == {"forward", "step", "backstep"}
    window.one_button.invoke()                  # still one step at a time
    assert window.mode == STEPS and on(window) == {"pause", "forward", "skip", "backstep"}


def test_after_the_program_has_ended_only_backstep_works(app, tmp_path):
    loaded(app, tmp_path, TWO_MOVES)
    window = connected(app)
    steps(app, 3)                               # SVC #10: the program ends
    to_end(window)
    assert app.runner.state is State.FINISHED and on(window) == {"backstep"}


def test_one_step_forward_runs_the_next_instruction_one_step_at_a_time(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    window.one_button.invoke()
    assert len(app.machine.history) == 1 and window.player.playing
    film = window.film
    to_end(window)                              # the clock goes on: the film waits
    first = film.steps[0]
    assert window.player.paused_at == pytest.approx(first.start + first.duration)
    window.one_button.invoke()                  # the next step of this film, not the next
    to_end(window)                              # instruction
    second = film.steps[1]
    assert len(app.machine.history) == 1 and window.film is film
    assert window.player.paused_at == pytest.approx(second.start + second.duration)
    assert sentence(window) == second.sentence


@pytest.mark.parametrize("number", [1, 4, 9])
def test_one_step_back_shows_exactly_the_picture_of_the_step_before(app, tmp_path, number):
    """From step number, waiting at its end, One step back shows what One step forward showed
    at the step before: every item the canvas shows (the strip and the panel with them), the
    strip's tips and the window inside a block."""
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 5)
    window.skip()                               # Step's film has ended: One step forward is on
    inside = window.open_inside("RegFile")
    forward_to(window, number - 1)
    wanted = shown(window), tips(window), shown(inside)
    app.run("backstep")                         # the same instruction once more
    forward_to(window, number)
    assert shown(window) != wanted[0]
    window.back_button.invoke()
    before = window.film.steps[number - 1]
    assert window.player.held and window.player.paused_at == before.start + before.duration
    assert (shown(window), tips(window), shown(inside)) == wanted


def test_one_step_back_within_a_step_goes_to_the_end_of_the_step_before(app, tmp_path):
    """Paused within step 3 (after Play, then Pause), One step back shows step 2; at the first
    step One step back is off."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    forward_to(window, 0)
    window.pause_button.invoke()                # Play
    film = window.film
    third = film.steps[3]
    at(window, third.start + third.duration / 2 - window.player.moment)
    window.pause_button.invoke()                # Pause, within step 3
    window.back_button.invoke()
    second = film.steps[2]
    assert window.player.held
    assert window.player.paused_at == pytest.approx(second.start + second.duration)
    assert sentence(window) == second.sentence
    window.back_button.invoke()
    window.back_button.invoke()
    first = film.steps[0]
    assert window.player.paused_at == pytest.approx(first.start + first.duration)
    assert window.back_button.instate(["disabled"])
    window.step_back()                          # off: nothing
    assert window.player.paused_at == pytest.approx(first.start + first.duration)


def test_play_from_the_middle_ends_as_skip_to_end_does(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 5)
    window.skip()
    forward_to(window, 3)
    window.pause_button.invoke()                # Play: from step 3 to the end
    assert window.player.playing and window.player.stop_at is None
    to_end(window)
    assert not window.player.playing and "What it did:" in panel(window)
    played = canvas_state(window), tips(window)
    app.run("backstep")
    forward_to(window, 3)
    window.skip_button.invoke()
    assert (canvas_state(window), tips(window)) == played


def test_one_step_back_after_the_end_goes_back_into_the_film(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    window.one_button.invoke()
    window.skip_button.invoke()                 # the film of One step forward has ended
    film = window.film
    assert "What it did:" in panel(window) and window.back_button.instate(["!disabled"])
    window.back_button.invoke()                 # back into it: its last step but one
    last_but_one = film.steps[-2]
    assert window.player.held
    assert window.player.paused_at == pytest.approx(last_but_one.start + last_but_one.duration)
    assert "What it did" not in panel(window) and window.tool_buttons["step"].instate(["disabled"])
    window.one_button.invoke()                  # it has not ended: its last step plays
    to_end(window)
    assert len(app.machine.history) == 1 and "What it did:" in panel(window)
    window.one_button.invoke()                  # ended again: the next instruction
    assert len(app.machine.history) == 2 and window.mode == STEPS


def test_the_tools_step_and_its_key_wait_for_the_film_to_end(app, tmp_path):
    """The toolbar's Step and F7 in the tool's window are off until a film has ended; the main
    window's Step works at all times: the next film plays whole."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    press_key(window.canvas, "<Key-F7>")
    window.tool_buttons["step"].invoke()
    window.one_button.invoke()
    assert len(app.machine.history) == 1 and window.player.playing
    app.run("step")                             # the main window's Step
    assert len(app.machine.history) == 2 and window.mode == WHOLE
    assert text_of(window, window.view_text).endswith("LDR R0, [R1, #4]")
    to_end(window)
    press_key(window.canvas, "<Key-F7>")        # ended: F7 runs the next instruction
    assert len(app.machine.history) == 3 and window.mode == WHOLE
    window.skip_button.invoke()
    window.one_button.invoke()                  # step by step: its first step
    assert len(app.machine.history) == 4 and window.mode == STEPS
    app.run("step")                             # the main window's Step ends that film
    assert len(app.machine.history) == 5 and window.mode == WHOLE and window.player.playing


def test_the_keys_o_b_e_and_space_and_r_does_nothing(app, tmp_path):
    window = opened(app)
    for key in ("<Key-o>", "<Key-b>", "<Key-e>"):     # no program: nothing happens
        assert press_key(window.canvas, key)[-1] == str(window.window)
    loaded(app, tmp_path, PROGRAM)
    window.connect_button.invoke()
    press_key(window.canvas, "<Key-o>")         # One step forward: LDR R1, =table
    assert len(app.machine.history) == 1 and window.mode == STEPS
    to_end(window)
    press_key(window.canvas, "<Key-O>")         # with Caps Lock: its second step
    to_end(window)
    film = window.film
    second, first = film.steps[1], film.steps[0]
    assert window.player.paused_at == pytest.approx(second.start + second.duration)
    press_key(window.canvas, "<Key-b>")         # One step back: the first step
    assert window.player.paused_at == pytest.approx(first.start + first.duration)
    for key in ("<Key-r>", "<Key-R>"):          # R is no key of the film any more
        assert press_key(window.canvas, key) == []
    assert window.player.held and len(app.machine.history) == 1
    press_key(window.canvas, "<space>")         # Play
    assert window.player.playing
    press_key(window.speed_scale, "<Key-e>")    # Skip to end, also from the slider
    assert not window.player.playing and "What it did:" in panel(window)
    assert window.speed_scale.get() == window.seconds
    press_key(window.canvas, "<Key-E>")         # off once the film has ended: nothing
    press_key(window.canvas, "<space>")
    assert not window.player.playing and len(app.machine.history) == 1


def test_step_by_step_a_read_goes_on_at_the_system_once_its_line_comes(app, tmp_path):
    loaded(app, tmp_path, READ)
    window = connected(app)
    steps(app, 2)
    window.skip()
    window.one_button.invoke()                  # SVC #8: the read waits for a line
    assert app.runner.state is State.WAITING and window.mode == STEPS
    while window._unfinished():                 # step by step to the system, which waits
        to_end(window)
        window.one_button.invoke()
    assert window.player.paused_at == pytest.approx(window.film.seconds)
    assert on(window) == {"back", "backstep"}
    type_line(app, "abc")                       # the line comes: the SVC ends
    run_until(app, lambda: app.runner.state is not State.WAITING)
    film = window.film
    system = next(number for number, step in enumerate(film.steps)
                  if step.lights and step.lights[0][0] == "System")
    assert window.mode == STEPS and window.player.playing
    assert window.player.moment == pytest.approx(film.steps[system].start)
    to_end(window)                              # the system's step again, then it waits
    end = film.steps[system].start + film.steps[system].duration
    assert window.player.held and window.player.paused_at == pytest.approx(end)
    assert "waits" not in film.steps[system].lights[0][1]
    window.one_button.invoke()                  # the steps after it, one at a time
    to_end(window)
    after = film.steps[system + 1]
    assert window.player.paused_at == pytest.approx(after.start + after.duration)


def test_replay_is_gone(app):
    window = opened(app)
    assert not hasattr(window, "replay_button") and not hasattr(window, "replay")
    assert "film_replay" not in icons.FILM and "film_back" in icons.FILM
    assert not any("Replay" in tip.text for tip in window.film_tips)
    assert "Replay" not in " ".join(tool.HELP.split())


@pytest.mark.parametrize("count", [5, 12], ids=["push", "pop"])
def test_one_step_forward_through_every_pass_ends_the_film(app, tmp_path, count):
    """PUSH {R4, R5, LR} and POP {R4, PC}: One step forward goes through the steps of every pass,
    one after another; at the last one the film has ended, as Skip to end leaves it."""
    loaded(app, tmp_path, MULTIPLE)
    window = connected(app)
    steps(app, count - 1)
    window.skip()
    window.one_button.invoke()
    film = window.film
    assert len(film.passes) > 1 and window.mode == STEPS
    last = len(film.steps) - 1
    for number in range(last + 1):
        to_end(window)
        assert window.player.paused_at == pytest.approx(film.steps[number].start
                                                        + film.steps[number].duration)
        if number < last:
            assert "What it did" not in panel(window) and window._unfinished(), number
            window.one_button.invoke()
    assert "What it did:" in panel(window) and window.player.paused_at == film.seconds
    assert on(window) == {"back", "forward", "step", "backstep"}


def test_one_step_back_from_the_first_step_of_a_pass_shows_the_pass_before(app, tmp_path):
    """From the first step of a PUSH's second pass, One step back shows the last step of the
    first pass: its heading, strip, tips and every item, as One step forward showed them."""
    loaded(app, tmp_path, MULTIPLE)
    window = connected(app)
    steps(app, 4)
    window.skip()
    window.one_button.invoke()                  # PUSH {R4, R5, LR}
    film = window.film
    window.skip_button.invoke()
    app.run("backstep")
    number = len(film.passes[0].steps)          # the first step of the second pass
    forward_to(window, number - 1)
    assert text_of(window, window.heading_item).endswith("PASS 1 OF 3")
    wanted = shown(window), tips(window)
    app.run("backstep")
    forward_to(window, number)
    assert text_of(window, window.heading_item).endswith("PASS 2 OF 3")
    window.back_button.invoke()
    assert text_of(window, window.heading_item).endswith("PASS 1 OF 3")
    assert (shown(window), tips(window)) == wanted


@pytest.mark.parametrize("how", ["assemble", "reset", "tool's reset", "backstep"])
def test_after_assemble_reset_or_backstep_no_film_is_left_unfinished(app, tmp_path, how):
    """A film going step by step, not ended: after Assemble, Reset (the main window's or the
    tool's) or Backstep, only Step and One step forward work of the film's buttons and Step;
    Backstep follows the main window."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 1)
    window.skip()
    window.one_button.invoke()
    to_end(window)
    window.one_button.invoke()
    assert window.mode == STEPS and window._unfinished()
    if how == "assemble":
        from test_gui_assemble import assemble
        assemble(app)
    elif how == "reset":
        app.run("reset")
    elif how == "tool's reset":
        window.reset_button.invoke()
    else:
        app.run("backstep")
    assert window.mode is None and not window.player.playing
    can_back = app.is_enabled("backstep")
    assert can_back == (how in ("tool's reset", "backstep"))
    assert on(window) == {"forward", "step"} | ({"backstep"} if can_back else set())


@pytest.mark.parametrize("seconds", [5, 40])
def test_step_by_step_goes_on_after_the_speed_or_the_size_changes(app, tmp_path, seconds):
    """Waiting at the end of a step when the slider moves or the picture is drawn again at
    another size, the film stays exactly at that step's end, and One step forward plays the
    next step; a step that plays meanwhile still stops at its own end."""
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 5)
    window.skip()
    forward_to(window, 3)
    window.speed_scale.set(seconds)
    window._speed_moved(seconds)                # a new film of the same steps
    film = window.film
    assert film.seconds == seconds and window.player.held
    assert window.player.paused_at == step_end(film, 3)
    window.one_button.invoke()
    to_end(window)
    assert window.player.paused_at == step_end(film, 4)
    window.rezoom(1.3)                          # drawn again at another size
    assert window.player.held and window.player.paused_at == step_end(window.film, 4)
    window.one_button.invoke()
    to_end(window)
    assert window.player.paused_at == step_end(window.film, 5)
    window.one_button.invoke()                  # step 6 plays: the slider moves meanwhile
    film = window.film
    step = film.steps[6]
    at(window, step.start + step.duration / 2 - window.player.moment)
    window.speed_scale.set(15)
    window._speed_moved(15)
    to_end(window)
    assert window.player.held and window.player.paused_at == step_end(window.film, 6)
