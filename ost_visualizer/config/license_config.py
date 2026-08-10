from pathlib import Path


def _load_trusted_public_key() -> str:
    bundled_key_path = Path(__file__).with_name("license_public_key.pem")
    if bundled_key_path.exists():
        return bundled_key_path.read_text(encoding="utf-8").strip()
    local_key_path = (
        Path(__file__).resolve().parents[2] / ".secrets" / "license_public_key.pem"
    )
    if local_key_path.exists():
        return local_key_path.read_text(encoding="utf-8").strip()
    return ""


LICENSE_OFFLINE_GRACE_HOURS = 72
LICENSE_VALIDATION_INTERVAL_SECONDS = 300
TRUSTED_LICENSE_PUBLIC_KEY_PEM = _load_trusted_public_key()
MAX_LICENSE_KEY_LENGTH = 80
MAX_HWID_LENGTH = 64
