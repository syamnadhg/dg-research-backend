"""CLI argument parsing — esp. that -v/--verbose works in BOTH positions."""

import pytest

from facade import cli


def _merged_verbose(argv):
    """Replicate main()'s merge of the before/after-subcommand -v positions."""
    ns = cli.build_parser().parse_args(argv)
    return getattr(ns, "verbose", False) or getattr(ns, "verbose_global", False)


def test_verbose_after_subcommand():
    assert _merged_verbose(["status", "-v"]) is True


def test_verbose_before_subcommand():
    # The bug this guards: a top-level -v used to be clobbered by the subparser
    # default and silently ignored.
    assert _merged_verbose(["-v", "status"]) is True
    assert _merged_verbose(["--verbose", "serve"]) is True


def test_verbose_absent_is_false():
    assert _merged_verbose(["status"]) is False


def test_login_remote_flags_parse():
    ns = cli.build_parser().parse_args(["login", "--remote", "--runtime", "hermes", "--label", "Scout"])
    assert ns.remote is True and ns.runtime == "hermes" and ns.label == "Scout"


def test_login_defaults_local():
    ns = cli.build_parser().parse_args(["login"])
    assert ns.remote is False


def test_device_bare_lists():
    ns = cli.build_parser().parse_args(["device"])
    assert ns.func is cli.cmd_device and ns.device_command is None


def test_device_list():
    ns = cli.build_parser().parse_args(["device", "list"])
    assert ns.func is cli.cmd_device and ns.device_command == "list"


def test_device_use_takes_id():
    ns = cli.build_parser().parse_args(["device", "use", "dev-123"])
    assert ns.func is cli.cmd_device and ns.device_command == "use" and ns.deviceId == "dev-123"


def test_research_parses_topic_and_flags():
    ns = cli.build_parser().parse_args(["research", "Tesla 2025", "--device", "d1", "--no-video"])
    assert ns.func is cli.cmd_research
    assert ns.topic == "Tesla 2025" and ns.device == "d1"
    assert ns.no_video is True and ns.no_email is False


def test_run_id_is_optional():
    a = cli.build_parser().parse_args(["run"])
    assert a.func is cli.cmd_run and a.runId is None
    b = cli.build_parser().parse_args(["run", "agent-x"])
    assert b.runId == "agent-x"


def test_runs_parses():
    assert cli.build_parser().parse_args(["runs"]).func is cli.cmd_runs


def test_podcast_id_is_optional():
    a = cli.build_parser().parse_args(["podcast"])
    assert a.func is cli.cmd_podcast and a.runId is None
    b = cli.build_parser().parse_args(["podcast", "agent-x"])
    assert b.runId == "agent-x"


def test_watch_id_is_optional():
    a = cli.build_parser().parse_args(["watch"])
    assert a.func is cli.cmd_watch and a.runId is None
    b = cli.build_parser().parse_args(["watch", "agent-x"])
    assert b.runId == "agent-x"


def test_cancel_requires_id():
    ns = cli.build_parser().parse_args(["cancel", "agent-x"])
    assert ns.func is cli.cmd_cancel and ns.runId == "agent-x"


def test_connect_parses():
    a = cli.build_parser().parse_args(["connect"])
    assert a.func is cli.cmd_connect and a.runtime is None
    b = cli.build_parser().parse_args(["connect", "hermes", "--dest", "/tmp/x"])
    assert b.runtime == "hermes" and b.dest == "/tmp/x"


def test_skip_parses_runid_and_phases():
    ns = cli.build_parser().parse_args(["skip", "agent-x", "1", "video"])
    assert ns.func is cli.cmd_skip and ns.runId == "agent-x" and ns.phases == ["1", "video"]


def test_stop_parses():
    assert cli.build_parser().parse_args(["stop"]).func is cli.cmd_stop


def test_autostart_action_required_and_validated():
    ns = cli.build_parser().parse_args(["autostart", "install"])
    assert ns.func is cli.cmd_autostart and ns.action == "install"
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["autostart", "frobnicate"])
