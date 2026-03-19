import pytest
import pytest_asyncio

from app.encryption import decrypt_token, encrypt_token


# Override autouse DB cleanup from conftest.py — these are pure unit tests
# that do not need a PostgreSQL connection.
@pytest_asyncio.fixture(autouse=True)
async def cleanup() -> None:  # type: ignore[override]
    yield  # type: ignore[misc]


@pytest.fixture(autouse=True)
def _set_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_SECRET_KEY", "test-secret-key-for-encryption")


class TestEncryptDecryptRoundTrip:
    def test_round_trip_returns_original(self) -> None:
        plaintext = "my-secret-token-12345"
        ciphertext = encrypt_token(plaintext)
        assert decrypt_token(ciphertext) == plaintext

    def test_different_plaintexts_produce_different_ciphertexts(self) -> None:
        ct1 = encrypt_token("token-aaa")
        ct2 = encrypt_token("token-bbb")
        assert ct1 != ct2

    def test_encrypted_output_differs_from_input(self) -> None:
        plaintext = "visible-value"
        ciphertext = encrypt_token(plaintext)
        assert ciphertext != plaintext

    def test_empty_string_round_trip(self) -> None:
        ciphertext = encrypt_token("")
        assert decrypt_token(ciphertext) == ""

    def test_long_string_round_trip(self) -> None:
        plaintext = "x" * 10_000
        ciphertext = encrypt_token(plaintext)
        assert decrypt_token(ciphertext) == plaintext

    def test_unicode_string_round_trip(self) -> None:
        plaintext = "Привет мир! \U0001f511 日本語テスト"
        ciphertext = encrypt_token(plaintext)
        assert decrypt_token(ciphertext) == plaintext
