import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

_TRANSIENT_ERRORS = (urllib.error.URLError, TimeoutError, OSError)


class LicenseApiClient:
    def __init__(
        self,
        base_url: str = "https://fabianhad.com/ost3d/api",
        timeout: int = 10,
        logger: Optional[logging.Logger] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)
        self._ssl_context = ssl.create_default_context()

    def validate(
        self, license_key: str, hwid: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        payload = {"license_key": license_key, "hwid": hwid}
        return self._post("validate", payload)

    def activate(
        self, license_key: str, hwid: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        payload = {"license_key": license_key, "hwid": hwid}
        return self._post("activate", payload)

    def deactivate(
        self, license_key: str, hwid: Optional[str]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        payload = {"license_key": license_key, "hwid": hwid}
        return self._post("deactivate", payload)

    def check_version(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        url = f"{self.base_url}/version"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self._ssl_context
            ) as response:
                response_data = self._decode_json_object(response.read(), "version")
                return (
                    (True, response_data)
                    if response_data is not None
                    else (False, None)
                )
        except urllib.error.HTTPError:
            return False, None
        except _TRANSIENT_ERRORS:
            return False, None

    def _post(
        self, endpoint: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        url = f"{self.base_url}/{endpoint}"
        json_data = json.dumps(payload).encode("utf-8")
        for attempt in range(2):
            request = urllib.request.Request(
                url,
                data=json_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout, context=self._ssl_context
                ) as response:
                    response_data = self._decode_json_object(response.read(), endpoint)
                    return (
                        (True, response_data)
                        if response_data is not None
                        else (False, None)
                    )
            except urllib.error.HTTPError as exc:
                if exc.code >= 500:
                    self.logger.warning("License API server error %s", exc.code)
                    return False, None
                try:
                    error_data = self._decode_json_object(exc.read(), endpoint)
                    return False, error_data
                except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                    self.logger.warning(
                        "License API error %s (no response body)", exc.code
                    )
                    return False, None
            except _TRANSIENT_ERRORS:
                if attempt == 0:
                    time.sleep(1)
        return False, None

    def _decode_json_object(
        self, response_body: bytes, context: str
    ) -> Optional[Dict[str, Any]]:
        try:
            response_data = json.loads(response_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.logger.warning("Invalid JSON from license API %s: %s", context, exc)
            return None
        if not isinstance(response_data, dict):
            self.logger.warning("Unexpected JSON shape from license API %s", context)
            return None
        return response_data
