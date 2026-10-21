from app.core.security import hash_password, verify_password, create_access_token

def test_password_hash_is_not_plaintext():
    hashed = hash_password("example-password-123")
    assert hashed != "example-password-123"
    assert verify_password("example-password-123", hashed)
    assert not verify_password("wrong-password", hashed)

def test_access_token_is_created():
    token = create_access_token(42)
    assert isinstance(token, str) and len(token) > 20
