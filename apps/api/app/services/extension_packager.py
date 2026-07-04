import json
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from app.config import settings

BrowserKind = Literal["chrome", "edge", "firefox", "brave", "opera", "chromium"]

EXTENSION_ROOT = Path(__file__).resolve().parents[3] / "extension"
EXTENSION_DIST = EXTENSION_ROOT / "dist"
GECKO_EXTENSION_ID = "career-os@applypilot.dev"


def _read_manifest_version() -> str:
    manifest_path = EXTENSION_DIST / "manifest.json"
    if not manifest_path.is_file():
        return "0.0.0"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return str(data.get("version", "0.0.0"))


def extension_info() -> dict[str, Any]:
    dist_ready = EXTENSION_DIST.is_dir() and (EXTENSION_DIST / "manifest.json").is_file()
    api_base = settings.career_os_api_public_url or "http://localhost:8000"
    store_urls = {
        "chrome": settings.career_os_chrome_web_store_url.strip() or None,
        "edge": settings.career_os_edge_addons_url.strip() or None,
        "firefox": settings.career_os_firefox_addons_url.strip() or None,
    }
    has_store = any(store_urls.values())
    return {
        "name": "CareerOS ApplyPilot",
        "version": _read_manifest_version(),
        "apiBaseUrl": api_base.rstrip("/"),
        "distReady": dist_ready,
        "distPath": str(EXTENSION_DIST),
        "supportedBrowsers": ["chrome", "edge", "brave", "opera", "firefox"],
        "installMode": "store" if has_store else "development",
        "storeUrls": store_urls,
        "installHint": (
            "Use Add to Chrome or Add to Firefox when store URLs are configured."
            if has_store
            else "Use Quick install on /features — download the package and load unpacked in your browser."
        ),
        "firefoxExtensionId": GECKO_EXTENSION_ID,
    }


def _firefox_manifest(original: dict[str, Any]) -> dict[str, Any]:
    patched = dict(original)
    patched["browser_specific_settings"] = {
        "gecko": {
            "id": GECKO_EXTENSION_ID,
            "strict_min_version": "128.0",
        }
    }
    host_permissions = list(patched.get("host_permissions", []))
    api_base = (settings.career_os_api_public_url or "http://localhost:8000").rstrip("/")
    if f"{api_base}/*" not in host_permissions:
        host_permissions.append(f"{api_base}/*")
    patched["host_permissions"] = host_permissions
    return patched


def _write_runtime_config(staging: Path, api_base: str, version: str) -> None:
    config = {
        "apiBaseUrl": api_base.rstrip("/"),
        "version": version,
        "wiredAt": "install",
    }
    (staging / "careeros-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def build_extension_zip(browser: BrowserKind = "chromium") -> tuple[bytes, str]:
    if not EXTENSION_DIST.is_dir():
        raise FileNotFoundError(
            f"Extension dist not found at {EXTENSION_DIST}. Run: pnpm --filter @career-os/extension build"
        )

    manifest = json.loads((EXTENSION_DIST / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest.get("version", "0.0.0"))
    api_base = (settings.career_os_api_public_url or "http://localhost:8000").rstrip("/")

    use_firefox = browser in ("firefox",)
    slug = "applypilot-firefox" if use_firefox else "applypilot-chromium"
    filename = f"careeros-{slug}-v{version}.zip"

    buffer = BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "applypilot"
        shutil.copytree(EXTENSION_DIST, staging)

        if use_firefox:
            ff_manifest = _firefox_manifest(manifest)
            (staging / "manifest.json").write_text(json.dumps(ff_manifest, indent=2), encoding="utf-8")

        _write_runtime_config(staging, api_base, version)

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in staging.rglob("*"):
                if file_path.is_file():
                    if use_firefox:
                        arcname = file_path.relative_to(staging)
                    else:
                        arcname = Path("applypilot") / file_path.relative_to(staging)
                    archive.write(file_path, arcname.as_posix())

    buffer.seek(0)
    return buffer.getvalue(), filename
