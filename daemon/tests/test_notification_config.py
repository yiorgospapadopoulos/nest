import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.config.errors import ConfigError
from harness.config.loader import load_settings, save_notifications
from harness.config.models import NotificationSettings, NtfySettings, QuietHours
from harness.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


def test_defaults_enable_agent_kinds_but_not_pr_checks_without_quiet_hours_or_ntfy() -> None:
    settings = NotificationSettings()

    assert settings.kinds.model_dump() == {
        "needs_approval": True,
        "question": True,
        "review_ready": True,
        "failed": True,
        "finished": True,
        # Pull request checks show in the inbox; pushing them is opt in (D034).
        "ci_failed": False,
        "ready_to_merge": False,
        # Stuck sessions show in the inbox; pushing them is opt in (D036).
        "stuck": False,
        # Pixie reports at or above each pixie's own severity (B42).
        "pixie_report": True,
    }
    assert settings.quiet_hours is None
    assert settings.ntfy.enabled is False
    assert settings.ntfy.server == "https://ntfy.sh"
    assert settings.vapid_subject.startswith("mailto:")


def test_notifications_are_read_from_settings(paths: AppPaths) -> None:
    paths.settings_file.write_text(
        '[notifications]\nvapid_subject = "https://example.org"\n'
        "[notifications.kinds]\nfinished = false\n"
        '[notifications.quiet_hours]\nstart = "22:30"\nend = "07:00"\n'
        '[notifications.ntfy]\nenabled = true\ntopic = "harness-k2v9x7q4m1z8"\n',
        encoding="utf-8",
    )

    settings = load_settings(paths).notifications

    assert settings.kinds.finished is False
    assert settings.kinds.failed is True
    assert settings.quiet_hours == QuietHours(start="22:30", end="07:00")
    assert settings.ntfy.topic == "harness-k2v9x7q4m1z8"
    assert settings.vapid_subject == "https://example.org"


@pytest.mark.parametrize(
    ("start", "end"), [("7:00", "08:00"), ("24:00", "07:00"), ("22:60", "07:00"), ("x", "y")]
)
def test_quiet_hours_need_hh_mm_times(start: str, end: str) -> None:
    with pytest.raises(ValidationError):
        QuietHours(start=start, end=end)


def test_quiet_hours_cannot_be_empty() -> None:
    with pytest.raises(ValidationError, match="differ"):
        QuietHours(start="08:00", end="08:00")


def test_enabled_ntfy_needs_a_topic() -> None:
    with pytest.raises(ValidationError, match="topic"):
        NtfySettings(enabled=True)


@pytest.mark.parametrize("topic", ["has space in a topic", "harness/k2v9x7q4m1z8", "x" * 65])
def test_ntfy_topics_are_url_safe(topic: str) -> None:
    with pytest.raises(ValidationError):
        NtfySettings(topic=topic)


def test_ntfy_topics_are_long_enough_to_be_hard_to_guess() -> None:
    """H-04: anyone who knows a public topic can read it."""
    assert NtfySettings(topic="k" * 16).topic == "k" * 16
    with pytest.raises(ValidationError, match="16"):
        NtfySettings(topic="harness-k2v9x7q")


@pytest.mark.parametrize("server", ["ftp://ntfy.sh", "ntfy.sh", "https://"])
def test_ntfy_server_must_be_http(server: str) -> None:
    with pytest.raises(ValidationError):
        NtfySettings(server=server)


@pytest.mark.parametrize("url", ["https://mac.ts.net", "http://localhost:8765"])
def test_ntfy_click_base_must_be_an_http_url_when_set(url: str) -> None:
    assert NtfySettings(click_base_url=url).click_base_url == url
    with pytest.raises(ValidationError):
        NtfySettings(click_base_url="mac.ts.net")


@pytest.mark.parametrize("subject", ["admin@example.org", "mailto:", "https://"])
def test_vapid_subject_is_mailto_or_https(subject: str) -> None:
    with pytest.raises(ValidationError):
        NotificationSettings(vapid_subject=subject)


def test_saving_replaces_only_the_notifications_section(paths: AppPaths) -> None:
    paths.settings_file.write_text(
        '[server]\nport = 9000\nallowed_origins = ["https://mac.ts.net"]\n'
        '[agents]\nmodel = "opus"\n[notifications.kinds]\nfinished = false\n',
        encoding="utf-8",
    )
    new = NotificationSettings.model_validate(
        {"kinds": {"question": False}, "quiet_hours": {"start": "23:00", "end": "06:30"}}
    )

    saved = save_notifications(paths, new)

    assert saved == new
    data = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert data["server"] == {"port": 9000, "allowed_origins": ["https://mac.ts.net"]}
    assert data["agents"] == {"model": "opus"}
    assert data["notifications"]["kinds"]["finished"] is True
    assert data["notifications"]["kinds"]["question"] is False
    assert data["notifications"]["quiet_hours"] == {"start": "23:00", "end": "06:30"}
    assert load_settings(paths).notifications == new
    assert list(paths.config_dir.glob("*.tmp")) == []


def test_saving_without_a_settings_file_creates_it(paths: AppPaths) -> None:
    save_notifications(paths, NotificationSettings())

    assert load_settings(paths).notifications == NotificationSettings()


def test_saving_refuses_to_overwrite_a_broken_settings_file(paths: AppPaths) -> None:
    paths.settings_file.write_text("[server\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid TOML"):
        save_notifications(paths, NotificationSettings())

    assert paths.settings_file.read_text(encoding="utf-8") == "[server\n"


def test_saving_refuses_when_other_sections_are_invalid(paths: AppPaths) -> None:
    paths.settings_file.write_text('[server]\nport = "x"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match=r"server\.port"):
        save_notifications(paths, NotificationSettings())
