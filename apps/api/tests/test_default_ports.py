"""Every shipped default must point at the ports the dev servers actually listen on.

Regression: setup scripts, the API .env template, config defaults, the extension
fallback and the README pointed at :8000 / :3000 while `pnpm dev` serves the API on
:4000 and the web app on :5000, so a fresh install had a dashboard that could not
reach its own API.
"""

import json
import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[3]


def _port(package: str) -> str:
    script = json.loads((ROOT / package / "package.json").read_text(encoding="utf-8"))["scripts"]["dev"]
    match = re.search(r"--port\s+(\d+)", script)
    assert match, f"no --port in {package} dev script"
    return match.group(1)


API_PORT = _port("apps/api")
WEB_PORT = _port("apps/web")
API_URL = f"http://localhost:{API_PORT}"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_setup_scripts_point_web_app_at_dev_api_port():
    for script in ("scripts/setup.ps1", "scripts/setup.sh"):
        urls = re.findall(r"NEXT_PUBLIC_API_URL=(http://localhost:\d+)", _read(script))
        assert urls, script
        # The value written into apps/web/.env.local (first occurrence) must be the live API.
        assert urls[0] == API_URL, f"{script} writes {urls[0]}, API listens on {API_URL}"


def test_setup_scripts_print_live_urls():
    for script in ("scripts/setup.ps1", "scripts/setup.sh"):
        text = _read(script)
        assert f"http://localhost:{WEB_PORT}/" in text, script
        assert f"{API_URL}/docs" in text, script


def test_env_templates_and_config_defaults_use_dev_api_port():
    assert f"CAREER_OS_API_PUBLIC_URL={API_URL}" in _read("apps/api/.env.example")
    assert f"NEXT_PUBLIC_API_URL={API_URL}" in _read(".env.example")
    assert Settings.model_fields["career_os_api_public_url"].default == API_URL


def test_extension_defaults_to_dev_api_port():
    assert f'DEFAULT_API_BASE = "{API_URL}"' in _read("apps/extension/src/shared/apiConfig.ts")
    manifest = json.loads(_read("apps/extension/manifest.json"))
    assert f"{API_URL}/*" in manifest["host_permissions"]


def test_readme_uses_live_ports_and_real_clone_url():
    readme = _read("README.md")
    assert "<careeros-repo-url>" not in readme
    assert "https://github.com/Oblivion-Labs-Dev/CareerOS" in readme
    assert "localhost:3000" not in readme and "localhost:8000" not in readme
    assert f"localhost:{WEB_PORT}" in readme and f"localhost:{API_PORT}" in readme
