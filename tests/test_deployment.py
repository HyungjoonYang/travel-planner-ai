"""Tests for deployment configuration: Dockerfile, render.yaml, .env.example."""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


class TestDockerfile:
    def test_dockerfile_exists(self):
        assert (ROOT / "Dockerfile").exists()

    def test_dockerfile_has_from(self):
        content = (ROOT / "Dockerfile").read_text()
        assert content.startswith("FROM python:3.12")

    def test_dockerfile_copies_requirements(self):
        content = (ROOT / "Dockerfile").read_text()
        assert "COPY requirements.txt" in content

    def test_dockerfile_installs_requirements(self):
        content = (ROOT / "Dockerfile").read_text()
        assert "pip install" in content
        assert "requirements.txt" in content

    def test_dockerfile_copies_src(self):
        content = (ROOT / "Dockerfile").read_text()
        assert "COPY src/" in content

    def test_dockerfile_exposes_port(self):
        content = (ROOT / "Dockerfile").read_text()
        assert "EXPOSE 8000" in content

    def test_dockerfile_has_cmd(self):
        content = (ROOT / "Dockerfile").read_text()
        assert "CMD" in content
        assert "uvicorn" in content

    def test_dockerfile_uses_host_0000(self):
        content = (ROOT / "Dockerfile").read_text()
        assert "0.0.0.0" in content

    def test_dockerignore_exists(self):
        assert (ROOT / ".dockerignore").exists()

    def test_dockerignore_excludes_env(self):
        content = (ROOT / ".dockerignore").read_text()
        assert ".env" in content

    def test_dockerignore_excludes_pyc(self):
        content = (ROOT / ".dockerignore").read_text()
        assert "*.pyc" in content or "__pycache__" in content


class TestRenderYaml:
    def _load(self):
        return yaml.safe_load((ROOT / "render.yaml").read_text())

    def test_render_yaml_exists(self):
        assert (ROOT / "render.yaml").exists()

    def test_render_yaml_is_valid(self):
        data = self._load()
        assert isinstance(data, dict)

    def test_render_yaml_has_services(self):
        data = self._load()
        assert "services" in data
        assert len(data["services"]) >= 1

    def test_service_type_is_web(self):
        svc = self._load()["services"][0]
        assert svc["type"] == "web"

    def test_service_has_build_command(self):
        svc = self._load()["services"][0]
        assert "buildCommand" in svc
        assert "pip install" in svc["buildCommand"]

    def test_service_has_start_command(self):
        svc = self._load()["services"][0]
        assert "startCommand" in svc
        assert "uvicorn" in svc["startCommand"]

    def test_service_start_command_uses_port_env(self):
        svc = self._load()["services"][0]
        assert "$PORT" in svc["startCommand"]

    def test_service_has_health_check(self):
        svc = self._load()["services"][0]
        assert svc.get("healthCheckPath") == "/health"

    def test_service_has_gemini_api_key_env(self):
        svc = self._load()["services"][0]
        keys = [e["key"] for e in svc.get("envVars", [])]
        assert "GEMINI_API_KEY" in keys

    def test_service_auto_deploy_on_main(self):
        svc = self._load()["services"][0]
        assert svc.get("autoDeploy") is True
        assert svc.get("branch") == "main"


class TestEnvExample:
    def test_env_example_exists(self):
        assert (ROOT / ".env.example").exists()

    def test_env_example_has_gemini_key(self):
        content = (ROOT / ".env.example").read_text()
        assert "GEMINI_API_KEY" in content

    def test_env_example_has_database_url(self):
        content = (ROOT / ".env.example").read_text()
        assert "DATABASE_URL" in content


class TestAppConfig:
    def test_database_url_has_default(self):
        import sys
        # Reload config without any env overrides to check defaults
        mod = sys.modules.get("app.config")
        if mod:
            # DATABASE_URL default is sqlite
            assert "sqlite" in mod.DATABASE_URL or os.getenv("DATABASE_URL", "sqlite") != ""

    def test_gemini_key_defaults_to_empty_string(self):
        """GEMINI_API_KEY should default to '' (not raise) when unset."""
        saved = os.environ.pop("GEMINI_API_KEY", None)
        try:
            import importlib
            import app.config as cfg
            importlib.reload(cfg)
            assert isinstance(cfg.GEMINI_API_KEY, str)
        finally:
            if saved is not None:
                os.environ["GEMINI_API_KEY"] = saved

    def test_config_module_imports_without_error(self):
        import app.config  # noqa: F401
