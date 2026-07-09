"""
security/hmac_custom.py

HMAC (Hash-based Message Authentication Code), built entirely on top of
our own sha256_digest() — no hmac library, no hashlib.

Algorithm (RFC 2104):
  1. If the key is longer than the hash's block size, hash it down first.
  2. If the key is shorter than the block size, pad it with zero bytes.
  3. HMAC(K, m) = H( (K XOR opad) || H( (K XOR ipad) || m ) )
     where ipad = 0x36 repeated block_size times,
           opad = 0x5c repeated block_size times.

This is what TOTP (security/totp.py) uses to turn a shared secret + a
time counter into a code that only someone holding the secret can
reproduce.
"""

from .hashing import sha256_digest

BLOCK_SIZE = 64  # SHA-256 operates on 64-byte (512-bit) blocks


def hmac_sha256(key: bytes, message: bytes) -> bytes:
    """Returns the 32-byte raw HMAC-SHA256 digest of `message` under `key`."""
    if len(key) > BLOCK_SIZE:
        key = sha256_digest(key)
    if len(key) < BLOCK_SIZE:
        key = key + b"\x00" * (BLOCK_SIZE - len(key))

    ipad = bytes(b ^ 0x36 for b in key)
    opad = bytes(b ^ 0x5C for b in key)

    inner_hash = sha256_digest(ipad + message)
    return sha256_digest(opad + inner_hash)


if __name__ == "__main__":
    # Cross-check against Python's built-in hmac module (which itself
    # doesn't implement hashing — it just orchestrates whatever hash
    # function you give it — so this is a fair, independent check of
    # our padding/inner-outer-hash logic).
    import hmac as stdlib_hmac
    import hashlib

    test_cases = [
        (b"key", b"The quick brown fox jumps over the lazy dog"),
        (b"", b"message with empty key"),
        (b"a_very_long_key_" * 10, b"short message"),  # exercises the "key > block size" path
        (b"12345678901234567890123456789012", b"\x00\x00\x00\x01"),  # TOTP-shaped input
    ]

    print("Validating our HMAC-SHA256 against Python's built-in hmac module...\n")
    all_passed = True
    for key, msg in test_cases:
        ours = hmac_sha256(key, msg).hex()
        theirs = stdlib_hmac.new(key, msg, hashlib.sha256).hexdigest()
        status = "PASS" if ours == theirs else "FAIL"
        if ours != theirs:
            all_passed = False
        print(f"[{status}] key={key[:20]!r} msg={msg[:30]!r}\n   ours:  {ours}\n   theirs:{theirs}\n")

    print("ALL TESTS PASSED" if all_passed else "SOME TESTS FAILED")
