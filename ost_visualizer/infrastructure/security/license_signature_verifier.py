import base64
import hashlib
import hmac
import logging
from typing import Optional, Tuple
from ...config.license_config import TRUSTED_LICENSE_PUBLIC_KEY_PEM

_SHA256_DIGEST_SIZE = 32
_RSA_ENCRYPTION_OID = b"\x2a\x86\x48\x86\xf7\x0d\x01\x01\x01"


class LicenseSignatureVerifier:
    def __init__(
        self,
        public_key_pem: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._public_key: Optional[Tuple[int, int]] = None
        pem = (
            public_key_pem
            if public_key_pem is not None
            else TRUSTED_LICENSE_PUBLIC_KEY_PEM
        )
        if pem:
            self._load_public_key(pem)

    def verify_license_payload(self, payload: dict, signature: Optional[str]) -> bool:
        if not self._public_key:
            self.logger.warning(
                "License signature verification unavailable: "
                "no trusted public key configured"
            )
            return False
        if not signature:
            self.logger.warning(
                "License signature verification failed: missing signature"
            )
            return False
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
        except (ValueError, TypeError) as exc:
            self.logger.warning(
                "License signature verification failed: invalid signature encoding (%s)",
                exc,
            )
            return False
        canonical = self._canonical_payload(payload)
        try:
            modulus, exponent = self._public_key
            if self._verify_rsa_pss_sha256(
                modulus, exponent, canonical, signature_bytes
            ):
                return True
            self.logger.warning("License signature verification failed")
            return False
        except Exception as exc:
            self.logger.warning("License signature verification failed: %s", exc)
            return False

    def _load_public_key(self, public_key_pem: str) -> None:
        try:
            self._public_key = self._parse_public_key_pem(public_key_pem)
        except ValueError as exc:
            self.logger.warning(
                "Trusted license public key could not be loaded: %s", exc
            )
            self._public_key = None

    @staticmethod
    def _verify_rsa_pss_sha256(
        modulus: int, exponent: int, message: bytes, signature: bytes
    ) -> bool:
        key_size = (modulus.bit_length() + 7) // 8
        if len(signature) != key_size:
            return False
        signature_int = int.from_bytes(signature, "big")
        if signature_int >= modulus:
            return False
        encoded = pow(signature_int, exponent, modulus).to_bytes(key_size, "big")
        return LicenseSignatureVerifier._verify_pss_encoded_message(
            encoded, modulus.bit_length() - 1, message
        )

    @staticmethod
    def _verify_pss_encoded_message(
        encoded: bytes, em_bits: int, message: bytes
    ) -> bool:
        em_len = len(encoded)
        hash_len = _SHA256_DIGEST_SIZE
        salt_len = em_len - hash_len - 2
        if salt_len < 0 or encoded[-1] != 0xBC:
            return False
        masked_db = encoded[: em_len - hash_len - 1]
        expected_zero_bits = 8 * em_len - em_bits
        if expected_zero_bits and masked_db[0] >> (8 - expected_zero_bits):
            return False
        digest = encoded[em_len - hash_len - 1 : em_len - 1]
        db_mask = LicenseSignatureVerifier._mgf1_sha256(digest, len(masked_db))
        db = bytes(left ^ right for left, right in zip(masked_db, db_mask))
        if expected_zero_bits:
            db = bytes([db[0] & (0xFF >> expected_zero_bits)]) + db[1:]
        if db[: em_len - hash_len - salt_len - 2] != b"\x00" * (
            em_len - hash_len - salt_len - 2
        ):
            return False
        if db[em_len - hash_len - salt_len - 2] != 0x01:
            return False
        salt = db[-salt_len:] if salt_len else b""
        message_hash = hashlib.sha256(message).digest()
        expected_digest = hashlib.sha256(b"\x00" * 8 + message_hash + salt).digest()
        return hmac.compare_digest(digest, expected_digest)

    @staticmethod
    def _mgf1_sha256(seed: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
            counter += 1
        return bytes(output[:length])

    @staticmethod
    def _parse_public_key_pem(public_key_pem: str) -> Tuple[int, int]:
        lines = []
        for raw_line in public_key_pem.strip().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("-----"):
                lines.append(line)
        if not lines:
            raise ValueError("empty PEM")
        try:
            der = base64.b64decode("".join(lines), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid PEM encoding") from exc
        parser = _DerReader(der)
        top = parser.read_sequence()
        if top.peek_tag() == 0x30:
            algorithm = top.read_sequence()
            oid = algorithm.read_oid()
            if oid != _RSA_ENCRYPTION_OID:
                raise ValueError("unsupported public key algorithm")
            if not algorithm.eof():
                algorithm.read_null()
            key_bits = top.read_bit_string()
            top.ensure_eof()
            return LicenseSignatureVerifier._parse_pkcs1_public_key(key_bits)
        modulus = top.read_integer()
        exponent = top.read_integer()
        top.ensure_eof()
        return modulus, exponent

    @staticmethod
    def _parse_pkcs1_public_key(der: bytes) -> Tuple[int, int]:
        parser = _DerReader(der)
        sequence = parser.read_sequence()
        modulus = sequence.read_integer()
        exponent = sequence.read_integer()
        sequence.ensure_eof()
        parser.ensure_eof()
        return modulus, exponent

    @staticmethod
    def _canonical_payload(payload: dict) -> bytes:
        license_key = payload.get("license_key") or ""
        expiry_date = payload.get("expiry_date") or ""
        hwid = payload.get("hwid") or ""
        return f"{license_key}:{expiry_date}:{hwid}".encode("utf-8")


class _DerReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def eof(self) -> bool:
        return self._offset == len(self._data)

    def ensure_eof(self) -> None:
        if not self.eof():
            raise ValueError("unexpected trailing public key data")

    def peek_tag(self) -> int:
        if self.eof():
            raise ValueError("unexpected end of public key data")
        return self._data[self._offset]

    def read_sequence(self) -> "_DerReader":
        return _DerReader(self._read_tlv(0x30))

    def read_integer(self) -> int:
        value = self._read_tlv(0x02)
        if not value:
            raise ValueError("invalid integer")
        return int.from_bytes(value, "big")

    def read_oid(self) -> bytes:
        return self._read_tlv(0x06)

    def read_null(self) -> None:
        value = self._read_tlv(0x05)
        if value:
            raise ValueError("invalid null")

    def read_bit_string(self) -> bytes:
        value = self._read_tlv(0x03)
        if not value or value[0] != 0:
            raise ValueError("unsupported public key bit string")
        return value[1:]

    def _read_tlv(self, expected_tag: int) -> bytes:
        if self.eof() or self._data[self._offset] != expected_tag:
            raise ValueError("invalid public key structure")
        self._offset += 1
        length = self._read_length()
        end = self._offset + length
        if end > len(self._data):
            raise ValueError("truncated public key data")
        value = self._data[self._offset : end]
        self._offset = end
        return value

    def _read_length(self) -> int:
        if self.eof():
            raise ValueError("truncated public key data")
        first = self._data[self._offset]
        self._offset += 1
        if first < 0x80:
            return first
        length_size = first & 0x7F
        if length_size == 0 or length_size > 4:
            raise ValueError("unsupported public key length")
        end = self._offset + length_size
        if end > len(self._data):
            raise ValueError("truncated public key data")
        length = int.from_bytes(self._data[self._offset : end], "big")
        self._offset = end
        return length
