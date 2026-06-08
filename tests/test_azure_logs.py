"""Azure log path resolution."""

from connectors import azure_logs


def test_live_paths_build_uses_execution_id():
    paths = azure_logs.live_paths_for_step("8098001", "build")
    assert paths[0] == "build_debug_logs_8098001/build.log"


def test_live_paths_deploy():
    paths = azure_logs.live_paths_for_step("123", "deploy")
    assert "deploy/deploy.log" in paths


def test_archive_read_paths_include_build_debug_dir(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "LOG_ARCHIVE_DIR", tmp_path)
    eid = "999"
    log_path = tmp_path / eid / f"build_debug_logs_{eid}" / "build.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("BUILD OK", encoding="utf-8")

    text = azure_logs.read_from_archive(eid, "share-uuid", "build")
    assert text == "BUILD OK"


def test_load_all_logs_concatenates_steps(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "LOG_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(config, "SKIP_AZURE_LIVE", True)
    eid = "888"
    (tmp_path / eid).mkdir()
    (tmp_path / eid / "securityTests.log").write_text("SEC ERR", encoding="utf-8")
    (tmp_path / eid / "deploy").mkdir()
    (tmp_path / eid / "deploy" / "deploy.log").write_text("DEPLOY OK", encoding="utf-8")

    combined = azure_logs.load_all_logs_for_execution(eid, "share-uuid")
    assert "=== securityTest ===" in combined
    assert "=== deploy ===" in combined
    assert "SEC ERR" in combined
