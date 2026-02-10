import datetime
from unittest.mock import MagicMock, patch

import pyotp
import pytest
from app.core.totp import RATE_LIMIT_attempts, decrypt_secret, encrypt_secret, verify_totp_code
from cryptography.fernet import Fernet


@pytest.fixture
def mock_settings():
    with patch("app.core.totp.settings") as mock:
        # Generate a valid key (url-safe base64)
        mock.totp_encryption_key = Fernet.generate_key().decode()
        mock.app_id = "test-app"
        yield mock

@pytest.fixture
def mock_firestore_client():
    with patch("app.core.totp.get_firestore_client") as mock:
        yield mock

@pytest.fixture(autouse=True)
def mock_firestore_transactional():
    # Mock the decorator to just return the function as is
    with patch("firebase_admin.firestore.transactional") as mock:
        mock.side_effect = lambda func: func
        yield mock

def test_encryption_decryption(mock_settings):
    secret = "JBSWY3DPEHPK3PXP"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    # Ensure it's different every time due to salt/iv if applicable, but Fernet guarantees that.
    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret

@pytest.mark.asyncio
async def test_verify_totp_success(mock_settings, mock_firestore_client):
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    token = totp.now()

    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db

    mock_doc_ref = MagicMock()
    # Chain of calls to get to the document reference
    mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref

    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction

    # Mock existing document
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True

    # Encrypt the secret using the same key as in settings
    f = Fernet(mock_settings.totp_encryption_key.encode())
    encrypted_secret = f.encrypt(secret.encode()).decode()

    mock_snapshot.to_dict.return_value = {
        "totp_enabled": True,
        "totp_secret_encrypted": encrypted_secret,
        "last_used_otp": "000000"
    }
    mock_doc_ref.get.return_value = mock_snapshot

    # Execute
    result = await verify_totp_code("admin_uid", token, "127.0.0.1")

    assert result is True

    # Verify transaction update was called with correct token
    mock_transaction.update.assert_called_once()
    args, _ = mock_transaction.update.call_args
    assert args[0] == mock_doc_ref
    assert args[1]["last_used_otp"] == token
    assert args[1]["totp_failed_attempts"] == 0

@pytest.mark.asyncio
async def test_verify_totp_failure_invalid_token(mock_settings, mock_firestore_client):
    secret = pyotp.random_base32()

    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db

    mock_doc_ref = MagicMock()
    mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref

    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction

    mock_snapshot = MagicMock()
    mock_snapshot.exists = True

    f = Fernet(mock_settings.totp_encryption_key.encode())
    encrypted_secret = f.encrypt(secret.encode()).decode()

    mock_snapshot.to_dict.return_value = {
        "totp_enabled": True,
        "totp_secret_encrypted": encrypted_secret,
        "last_used_otp": "000000",
        "totp_failed_attempts": 0
    }
    mock_doc_ref.get.return_value = mock_snapshot

    # Invalid token
    invalid_token = "123456"

    result = await verify_totp_code("admin_uid", invalid_token, "127.0.0.1")

    assert result is False
    mock_transaction.update.assert_called_once()
    args, _ = mock_transaction.update.call_args
    assert args[1]["totp_failed_attempts"] == 1

@pytest.mark.asyncio
async def test_verify_totp_replay_attack(mock_settings, mock_firestore_client):
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    token = totp.now()

    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db

    mock_doc_ref = MagicMock()
    mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref

    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction

    mock_snapshot = MagicMock()
    mock_snapshot.exists = True

    f = Fernet(mock_settings.totp_encryption_key.encode())
    encrypted_secret = f.encrypt(secret.encode()).decode()

    # Simulate replay: last_used_otp matches current token
    mock_snapshot.to_dict.return_value = {
        "totp_enabled": True,
        "totp_secret_encrypted": encrypted_secret,
        "last_used_otp": token
    }
    mock_doc_ref.get.return_value = mock_snapshot

    result = await verify_totp_code("admin_uid", token, "127.0.0.1")

    assert result is False
    # Replay should NOT increment failed attempts usually, or should it?
    # Code logs replay but returns False.
    mock_transaction.update.assert_not_called()

@pytest.mark.asyncio
async def test_verify_totp_not_enabled(mock_settings, mock_firestore_client):
    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db
    mock_doc_ref = MagicMock()
    mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref
    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction

    mock_snapshot = MagicMock()
    mock_snapshot.exists = True
    mock_snapshot.to_dict.return_value = {
        "totp_enabled": False
    }
    mock_doc_ref.get.return_value = mock_snapshot

    result = await verify_totp_code("admin_uid", "123456", "127.0.0.1")
    assert result is False

@pytest.mark.asyncio
async def test_verify_totp_rate_limiting(mock_settings, mock_firestore_client):
    secret = pyotp.random_base32()

    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db
    mock_doc_ref = MagicMock()
    mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc_ref
    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction

    mock_snapshot = MagicMock()
    mock_snapshot.exists = True
    f = Fernet(mock_settings.totp_encryption_key.encode())
    encrypted_secret = f.encrypt(secret.encode()).decode()

    # 3 failed attempts already
    last_failed = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=10) # 10 seconds ago

    mock_snapshot.to_dict.return_value = {
        "totp_enabled": True,
        "totp_secret_encrypted": encrypted_secret,
        "totp_failed_attempts": RATE_LIMIT_attempts,
        "totp_last_failed_at": last_failed.isoformat(),
        "last_used_otp": "000000"
    }
    mock_doc_ref.get.return_value = mock_snapshot

    # Even with valid token, it should fail due to rate limit
    totp = pyotp.TOTP(secret)
    token = totp.now()

    result = await verify_totp_code("admin_uid", token, "127.0.0.1")

    assert result is False
    mock_transaction.update.assert_not_called()
