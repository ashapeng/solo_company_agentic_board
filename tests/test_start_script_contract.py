from pathlib import Path


def test_start_script_scopes_uvicorn_reload_to_server_code():
    script = Path("start.sh").read_text(encoding="utf-8")

    assert "--reload-dir server" in script
    assert "--reload-dir tests" not in script
