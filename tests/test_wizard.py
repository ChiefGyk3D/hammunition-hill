# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""`hamhill setup`, driven end to end with canned answers.

Every test runs the real interview and the real renderer; the only fake is
the keyboard. The load-bearing property: whatever the answers, the produced
config must pass the same validation `hamhill check` runs -- a wizard that
can emit a config the validator refuses is worse than no wizard, because it
teaches a beginner that the tool is broken when it is the tool's author.
"""

import tomllib

import pytest

from hammunition_hill.config import parse_config
from hammunition_hill.wizard import interview, render_config, run, summarize


class Script:
    """Answers questions in order by matching a fragment of the prompt."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.transcript = []

    def ask(self, prompt, default=""):
        self.transcript.append(prompt)
        for i, (fragment, reply) in enumerate(self.answers):
            if fragment.lower() in prompt.lower():
                self.answers.pop(i)
                return reply
        return default

    def say(self, line):
        self.transcript.append(line)


def config_from(answers):
    script = Script(answers)
    filled = interview(script.ask, script.say)
    return render_config(filled), filled, script


ALL_DEFAULTS: list = []


def test_pressing_enter_all_the_way_gives_a_working_config(tmp_path):
    text, answers, _ = config_from(ALL_DEFAULTS)
    config = parse_config(tomllib.loads(text), base_dir=tmp_path)

    assert config.server.host == "127.0.0.1"
    ids = [s.id for s in config.sources]
    assert "hamqsl" in ids and "pota" in ids and "protons" in ids
    # Nothing that sends the callsign is on by default.
    assert not {"cluster", "rbn", "pskreporter", "wspr"} & set(ids)


def test_the_full_yes_path_parses_and_carries_the_callsign(tmp_path):
    text, answers, _ = config_from(
        [
            ("your callsign", "W1AW"),
            ("grid square", "FN31pr"),
            ("licence class", "extra"),
            ("nws weather alerts", "CT"),
            ("dx cluster spots", "y"),
            ("cluster node", "dxc.example.net:7300"),
            ("reverse beacon", "y"),
            ("psk reporter", "y"),
            ("wspr", "y"),
            ("wsjt-x", "y"),
            ("rigctld", "y"),
            ("adif log", "logs/mylog.adi"),
        ]
    )
    config = parse_config(tomllib.loads(text), base_dir=tmp_path)

    assert config.station["callsign"] == "W1AW"
    assert config.station["grid"] == "FN31PR"
    by_id = {s.id: s for s in config.sources}
    assert by_id["cluster"].options["callsign"] == "W1AW"
    assert by_id["rbn"].options["watch"] == ["W1AW"]
    assert by_id["pskreporter"].options["callsign"] == "W1AW"
    assert "area=CT" in by_id["wxalerts"].url
    assert by_id["wsjtx"].local and by_id["rig"].local


def test_a_bad_grid_is_reprompted_not_accepted():
    _, answers, script = config_from([("grid square", "not-a-grid"), ("try again", "FN31")])
    assert answers.grid == "FN31"
    assert any("does not look right" in line for line in script.transcript)


def test_declining_everything_still_validates(tmp_path):
    text, answers, _ = config_from([("space weather", "n"), ("activity", "n")])
    config = parse_config(tomllib.loads(text), base_dir=tmp_path)
    assert config.sources == ()  # tier 0 only, and the server test proves that serves


def test_lan_answer_binds_wide_and_the_summary_warns():
    _, answers, _ = config_from([("beyond this machine", "y")])
    assert answers.lan
    warning = [line for line in summarize(answers) if "0.0.0.0" in line]
    assert warning and "NO login" in warning[0]


def test_summary_names_every_callsign_recipient():
    _, answers, _ = config_from([("reverse beacon", "y"), ("psk reporter", "y")])
    joined = "\n".join(summarize(answers))
    assert "Reverse Beacon Network" in joined and "pskreporter.info" in joined
    assert "wspr" not in joined.lower()


def test_run_refuses_to_clobber_without_a_yes(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text("# precious\n")
    script = Script([("overwrite", "n")])

    assert run(target, script.ask, script.say) == 1
    assert target.read_text() == "# precious\n"


def test_run_backs_up_before_overwriting(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text("# precious\n")
    script = Script([("overwrite", "y"), ("write this config", "y")])

    assert run(target, script.ask, script.say) == 0
    assert (tmp_path / "config.toml.bak").read_text() == "# precious\n"
    assert "[station]" in target.read_text()


def test_run_writes_nothing_when_the_final_answer_is_no(tmp_path):
    target = tmp_path / "config.toml"
    script = Script([("write this config", "n")])

    assert run(target, script.ask, script.say) == 1
    assert not target.exists()


@pytest.mark.parametrize(
    "answers",
    [
        [("your callsign", "VE3/W1AW")],
        [("grid square", "fn31")],
        [("nws weather alerts", "ny")],
    ],
)
def test_odd_but_legal_answers_still_produce_a_valid_config(tmp_path, answers):
    text, _, _ = config_from(answers)
    parse_config(tomllib.loads(text), base_dir=tmp_path)
