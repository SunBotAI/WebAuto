"""WebAuto v3 packaging and architecture baseline tests."""

from pathlib import Path


def test_webauto_package_exposes_v3_version() -> None:
    import webauto

    assert webauto.__version__.startswith("3.")


def test_layered_packages_are_importable() -> None:
    import webauto.adapters
    import webauto.agent
    import webauto.application
    import webauto.domain
    import webauto.runtime
    import webauto.runtime.browser
    import webauto.storage


def test_runtime_layout_keeps_secrets_out_of_source_tree() -> None:
    from webauto.config import RuntimeSettings

    settings = RuntimeSettings.from_env(
        env={"WEBAUTO_RUNTIME_DIR": "var-test", "WEBAUTO_DATABASE_URL": "postgresql://secret"},
        project_root=Path("/workspace"),
    )

    assert settings.runtime_dir == Path("/workspace/var-test")
    assert "secret" not in repr(settings)
    assert settings.database_url.get_secret_value() == "postgresql://secret"
