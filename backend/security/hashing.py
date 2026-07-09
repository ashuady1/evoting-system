"""
security/hashing.py

SHA-256 implemented from scratch — no hashlib, no cryptography library.
This is the algorithm exactly as specified in FIPS 180-4.

WHY WE DON'T HAND-ROLL RANDOMNESS TOO:
Salts are generated with os.urandom(), which calls the operating system's
CSPRNG. This is NOT "using a crypto library to do our job for us" — it's
the OS-level entropy source that even production crypto libraries rely on.
Implementing a secure random number generator from scratch would mean
writing our own entropy collection, which is a genuinely different (and
genuinely dangerous to get wrong) problem from implementing a hash
algorithm. We draw the line at: algorithms = ours, entropy source = OS.
This distinction is worth stating explicitly in the report.
"""

import os

# ---------------------------------------------------------------------------
# Constants defined by the SHA-256 specification (FIPS 180-4)
# ---------------------------------------------------------------------------

# First 32 bits of the fractional parts of the square roots of the first
# 8 primes (2, 3, 5, 7, 11, 13, 17, 19).
_H_INIT = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]

# First 32 bits of the fractional parts of the cube roots of the first
# 64 primes (2 .. 311).
_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]

_MASK32 = 0xFFFFFFFF


def _right_rotate(value, bits):
    """32-bit right rotation: bits wrap around instead of dropping off."""
    return ((value >> bits) | (value << (32 - bits))) & _MASK32


def _pad_message(message: bytes) -> bytes:
    """
    Pads the message per the spec:
    1. Append a single '1' bit (0x80 byte, since we work byte-aligned).
    2. Append '0' bits until length % 512 == 448 (i.e. 56 bytes into a 64-byte block).
    3. Append the original message length as a 64-bit big-endian integer (in bits).
    """
    original_bit_length = len(message) * 8
    message += b"\x80"
    while len(message) % 64 != 56:
        message += b"\x00"
    message += original_bit_length.to_bytes(8, byteorder="big")
    return message


def sha256_digest(message: bytes) -> bytes:
    """
    Same algorithm as sha256() below, but returns the raw 32 bytes instead
    of a hex string. HMAC (and anything else that chains hash calls
    together) needs the raw bytes, not a hex-encoded string.
    """
    padded = _pad_message(message)
    h = list(_H_INIT)  # working copy of the 8 hash state words

    # Process the message in 64-byte (512-bit) chunks.
    for chunk_start in range(0, len(padded), 64):
        chunk = padded[chunk_start:chunk_start + 64]

        # --- Build the 64-word message schedule ---
        w = [0] * 64
        for i in range(16):
            w[i] = int.from_bytes(chunk[i * 4:i * 4 + 4], byteorder="big")
        for i in range(16, 64):
            s0 = _right_rotate(w[i - 15], 7) ^ _right_rotate(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _right_rotate(w[i - 2], 17) ^ _right_rotate(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w[i] = (w[i - 16] + s0 + w[i - 7] + s1) & _MASK32

        # --- Initialize working variables for this chunk ---
        a, b, c, d, e, f, g, hh = h

        # --- Main compression loop: 64 rounds ---
        for i in range(64):
            s1 = _right_rotate(e, 6) ^ _right_rotate(e, 11) ^ _right_rotate(e, 25)
            ch = (e & f) ^ ((~e & _MASK32) & g)
            temp1 = (hh + s1 + ch + _K[i] + w[i]) & _MASK32

            s0 = _right_rotate(a, 2) ^ _right_rotate(a, 13) ^ _right_rotate(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            temp2 = (s0 + maj) & _MASK32

            hh = g
            g = f
            f = e
            e = (d + temp1) & _MASK32
            d = c
            c = b
            b = a
            a = (temp1 + temp2) & _MASK32

        # --- Add this chunk's result into the running hash state ---
        h[0] = (h[0] + a) & _MASK32
        h[1] = (h[1] + b) & _MASK32
        h[2] = (h[2] + c) & _MASK32
        h[3] = (h[3] + d) & _MASK32
        h[4] = (h[4] + e) & _MASK32
        h[5] = (h[5] + f) & _MASK32
        h[6] = (h[6] + g) & _MASK32
        h[7] = (h[7] + hh) & _MASK32

    return b"".join(word.to_bytes(4, byteorder="big") for word in h)


def sha256(message: bytes) -> str:
    """
    Computes the SHA-256 hash of `message` and returns it as a 64-character
    lowercase hex string — same format as hashlib.sha256(message).hexdigest().
    """
    return sha256_digest(message).hex()


# ---------------------------------------------------------------------------
# Salting helpers — used for both student ID hashing and password hashing
# ---------------------------------------------------------------------------

def generate_salt(length: int = 16) -> str:
    """Returns a random hex-encoded salt using the OS's CSPRNG."""
    return os.urandom(length).hex()


def hash_with_salt(data: str, salt: str) -> str:
    """Hashes `data` combined with `salt` using our from-scratch SHA-256."""
    combined = (salt + data).encode("utf-8")
    return sha256(combined)


def verify_hash(data: str, salt: str, expected_hash: str) -> bool:
    """Recomputes the salted hash and checks it matches what's stored."""
    return hash_with_salt(data, salt) == expected_hash


if __name__ == "__main__":
    # Quick self-test if you run this file directly: `python security/hashing.py`
    import hashlib

    test_cases = [b"", b"abc", b"student_id_79010020", b"a" * 1000]
    print("Validating our SHA-256 against Python's built-in hashlib...\n")
    all_passed = True
    for case in test_cases:
        ours = sha256(case)
        theirs = hashlib.sha256(case).hexdigest()
        status = "PASS" if ours == theirs else "FAIL"
        if ours != theirs:
            all_passed = False
        label = case[:30]
        print(f"[{status}] input={label!r}\n   ours:  {ours}\n   theirs:{theirs}\n")

    print("ALL TESTS PASSED" if all_passed else "SOME TESTS FAILED")
