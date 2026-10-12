from irus import cli, party, web


def test_host_does_not_share_files_by_default(tmp_path, monkeypatch):
    args = cli.build_parser().parse_args(["host", str(tmp_path), "--address", "127.0.0.1"])
    captured = []
    monkeypatch.setattr(party, "pick_port", lambda port: 8787)
    monkeypatch.setattr(web, "TOKEN", "test-only")
    monkeypatch.setattr(web, "SHARE_ROOT", tmp_path)
    monkeypatch.setattr(cli, "cmd_watch", lambda options: captured.append(options) or 0)

    assert cli.cmd_host(args) == 0
    assert captured[0].share_files is False
    assert web.SHARE_ROOT is None


def test_host_requires_explicit_file_sharing_flag():
    parser = cli.build_parser()
    assert parser.parse_args(["host"]).no_files is True
    assert parser.parse_args(["host", "--share-files"]).no_files is False
    assert parser.parse_args(["host", "--no-files"]).no_files is True


def test_interactive_host_asks_before_sharing_files(monkeypatch):
    answers = iter(["1", ".", "n"])
    captured = []
    monkeypatch.setattr(party, "ask", lambda *args: next(answers))
    monkeypatch.setattr(cli, "cmd_host", lambda options: captured.append(options) or 0)

    assert cli.interactive() == 0
    assert captured[0].no_files is True
