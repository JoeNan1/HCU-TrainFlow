from hcu_trainflow.cli import parser
from hcu_trainflow.command_registry import MODULAR_COMMANDS


def test_modular_commands_are_registered_and_dispatched_separately():
    commands = set(parser()._subparsers._group_actions[0].choices)
    assert MODULAR_COMMANDS <= commands


def test_blocked_capability_is_not_a_successful_cli_exit(tmp_path, monkeypatch, capsys):
    from hcu_trainflow import cli
    monkeypatch.setattr(cli, "execute", lambda args: {"status": "blocked"})
    assert cli.main(["--workspace", str(tmp_path), "capability-list"]) == 2
    assert '"blocked"' in capsys.readouterr().out
