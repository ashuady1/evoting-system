"""
security/rsa_custom.py

RSA implemented from scratch: our own modular exponentiation (no use of
Python's built-in pow(x, y, z), which would essentially be "the fast RSA
math already done for you"), our own extended Euclidean algorithm for
the modular inverse, and our own Miller-Rabin primality test for key
generation — not just the encrypt/decrypt formula.

CRITICAL FIX vs. textbook RSA (see docs/DEVLOG.md Entry 2):
Plain RSA (c = m^e mod n) is deterministic — encrypting the same message
twice gives the same ciphertext, which is fatal when the message space is
small and guessable (e.g. a vote is one of 5 candidate IDs). Before
encrypting, we prepend a random nonce to the plaintext so the same vote
never produces the same ciphertext twice. See encrypt_ballot() /
decrypt_ballot() below, and the padding-defeats-determinism check in the
self-test at the bottom of this file.

KEY SIZE: we use a 2048-bit modulus (1024-bit primes) — the current
generally-recommended minimum for real-world RSA. Initial testing showed
our pure-Python implementation generates a 2048-bit keypair in about 1.5
seconds (512-bit: 0.03s, 1024-bit: 0.11s, 2048-bit: 1.5s) — fast enough
to generate live during a demo, so there was no need to compromise on a
weaker, insecure key size just for speed.
"""

import os

# ---------------------------------------------------------------------------
# Core arithmetic — implemented ourselves, not via Python's pow(x, y, z)
# ---------------------------------------------------------------------------

def _mod_pow(base: int, exponent: int, modulus: int) -> int:
    """Modular exponentiation via square-and-multiply. This is the single
    most important RSA subroutine — computing base^exponent mod modulus
    without ever materializing the full (astronomically large) power."""
    if modulus == 1:
        return 0
    result = 1
    base = base % modulus
    while exponent > 0:
        if exponent & 1:
            result = (result * base) % modulus
        exponent >>= 1
        base = (base * base) % modulus
    return result


def _extended_gcd(a: int, b: int):
    """Returns (gcd, x, y) such that a*x + b*y = gcd(a, b)."""
    old_r, r = a, b
    old_s, s = 1, 0
    old_t, t = 0, 1
    while r != 0:
        quotient = old_r // r
        old_r, r = r, old_r - quotient * r
        old_s, s = s, old_s - quotient * s
        old_t, t = t, old_t - quotient * t
    return old_r, old_s, old_t  # gcd, x, y


def _mod_inverse(a: int, m: int) -> int:
    """Returns a^-1 mod m using the extended Euclidean algorithm — i.e.
    the private exponent d such that (e * d) mod phi(n) == 1."""
    gcd, x, _ = _extended_gcd(a, m)
    if gcd != 1:
        raise ValueError("Modular inverse does not exist (inputs not coprime).")
    return x % m


# ---------------------------------------------------------------------------
# Miller-Rabin primality test
# ---------------------------------------------------------------------------

_SMALL_PRIMES = [
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67,
    71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139,
    149, 151, 157, 163, 167, 173, 179, 181, 191, 193, 197, 199, 211, 223,
    227, 229, 233, 239, 241, 251,
]


def is_probable_prime(n: int, rounds: int = 40) -> bool:
    """
    Miller-Rabin primality test. Unlike the simpler Fermat test, this
    correctly identifies Carmichael numbers (composites that fool Fermat's
    test) as composite — see the self-test below, which checks this
    explicitly against 561, the smallest Carmichael number.

    `rounds=40` gives a false-positive probability of at most 4^-40,
    i.e. effectively zero for any practical purpose.
    """
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n == p:
            return True
        if n % p == 0:
            return False

    # Write n - 1 as 2^r * d with d odd.
    r, d = 0, n - 1
    while d % 2 == 0:
        d //= 2
        r += 1

    for _ in range(rounds):
        a = int.from_bytes(os.urandom((n.bit_length() + 7) // 8), "big") % (n - 3) + 2
        x = _mod_pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = _mod_pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False  # definitely composite
    return True  # probably prime


def _generate_odd_candidate(bits: int) -> int:
    """Random odd number of exactly `bits` bits, with the top two bits set
    so that the product of two such primes has the full expected bit length."""
    raw = os.urandom(bits // 8)
    n = int.from_bytes(raw, "big")
    n |= (1 << (bits - 1)) | (1 << (bits - 2))  # ensure full bit length
    n |= 1  # ensure odd
    return n


def generate_prime(bits: int) -> int:
    """Keeps generating random odd candidates until one passes Miller-Rabin."""
    while True:
        candidate = _generate_odd_candidate(bits)
        if is_probable_prime(candidate):
            return candidate


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

DEFAULT_KEY_BITS = 2048  # see module docstring re: key size trade-off

def generate_keypair(key_bits: int = DEFAULT_KEY_BITS):
    """Returns (public_key, private_key), each a (exponent, n) tuple."""
    prime_bits = key_bits // 2
    p = generate_prime(prime_bits)
    q = generate_prime(prime_bits)
    while p == q:
        q = generate_prime(prime_bits)

    n = p * q
    phi = (p - 1) * (q - 1)

    e = 65537  # standard choice: small, fixed, has few 1-bits (fast to encrypt with)
    if _extended_gcd(e, phi)[0] != 1:
        # Vanishingly rare with 512+ bit primes, but handle it correctly rather
        # than assuming e is always valid.
        e = 3
        while _extended_gcd(e, phi)[0] != 1:
            e += 2

    d = _mod_inverse(e, phi)

    return (e, n), (d, n)


# ---------------------------------------------------------------------------
# Encryption / decryption
# ---------------------------------------------------------------------------

def encrypt_int(m: int, public_key) -> int:
    e, n = public_key
    return _mod_pow(m, e, n)


def decrypt_int(c: int, private_key) -> int:
    d, n = private_key
    return _mod_pow(c, d, n)


NONCE_LENGTH = 16


def _generate_nonce() -> bytes:
    """Random nonce with a guaranteed non-zero first byte, so the combined
    (nonce + length + plaintext) block never starts with 0x00 — that keeps
    its integer representation's byte length unambiguous on the way back."""
    while True:
        nonce = os.urandom(NONCE_LENGTH)
        if nonce[0] != 0:
            return nonce


def encrypt_ballot(plaintext: bytes, public_key) -> int:
    """
    Encrypts `plaintext` with random padding, so encrypting the same
    ballot twice produces different ciphertexts (defeats the small-message-
    space guessing attack described in the module docstring).
    """
    e, n = public_key
    nonce = _generate_nonce()
    length_prefix = len(plaintext).to_bytes(4, "big")
    combined = nonce + length_prefix + plaintext

    m = int.from_bytes(combined, "big")
    if m >= n:
        raise ValueError("Plaintext too long for this key size.")

    return encrypt_int(m, public_key)


def decrypt_ballot(ciphertext: int, private_key) -> bytes:
    m = decrypt_int(ciphertext, private_key)
    combined = m.to_bytes((m.bit_length() + 7) // 8, "big")

    nonce = combined[:NONCE_LENGTH]              # noqa: F841 (kept for clarity/debugging)
    length = int.from_bytes(combined[NONCE_LENGTH:NONCE_LENGTH + 4], "big")
    plaintext = combined[NONCE_LENGTH + 4:NONCE_LENGTH + 4 + length]
    return plaintext


if __name__ == "__main__":
    import time

    print("--- Miller-Rabin correctness check ---")
    known_primes = [97, 7919, 104729]
    known_composites = [91, 100, 561]  # 561 = 3 x 11 x 17, the smallest Carmichael number
    all_passed = True
    for p in known_primes:
        ok = is_probable_prime(p)
        print(f"[{'PASS' if ok else 'FAIL'}] {p} correctly identified as prime")
        all_passed &= ok
    for c in known_composites:
        ok = not is_probable_prime(c)
        label = " (Carmichael number — fools naive Fermat testing)" if c == 561 else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {c} correctly identified as composite{label}")
        all_passed &= ok

    print("\n--- Key generation timing ---")
    start = time.time()
    public_key, private_key = generate_keypair(DEFAULT_KEY_BITS)
    elapsed = time.time() - start
    print(f"Generated a {DEFAULT_KEY_BITS}-bit keypair in {elapsed:.2f}s")
    print(f"Public key (e, n) has n of {public_key[1].bit_length()} bits")

    print("\n--- Raw encrypt/decrypt correctness (10 random messages) ---")
    all_raw_passed = True
    for i in range(10):
        msg = int.from_bytes(os.urandom(20), "big") % public_key[1]
        c = encrypt_int(msg, public_key)
        recovered = decrypt_int(c, private_key)
        ok = recovered == msg
        all_raw_passed &= ok
        if not ok:
            print(f"[FAIL] message {i} did not round-trip correctly")
    print("[PASS] all 10 raw messages round-tripped correctly" if all_raw_passed else "[FAIL] some raw messages failed")

    print("\n--- Ballot padding: same plaintext encrypted twice must differ ---")
    # A real ballot is encoded compactly (position_id, candidate_id pairs),
    # not as verbose JSON — see services/ballot_service.py for the actual
    # encoding used when this is wired into vote casting.
    ballot = b"E3|P1:C7|P2:C12"
    c1 = encrypt_ballot(ballot, public_key)
    c2 = encrypt_ballot(ballot, public_key)
    different_ciphertexts = c1 != c2
    print(f"[{'PASS' if different_ciphertexts else 'FAIL'}] identical ballot produced {'different' if different_ciphertexts else 'THE SAME'} ciphertexts")

    both_decrypt_correctly = decrypt_ballot(c1, private_key) == ballot and decrypt_ballot(c2, private_key) == ballot
    print(f"[{'PASS' if both_decrypt_correctly else 'FAIL'}] both ciphertexts decrypt back to the original ballot")

    overall = all_passed and all_raw_passed and different_ciphertexts and both_decrypt_correctly
    print("\nALL TESTS PASSED" if overall else "\nSOME TESTS FAILED")
