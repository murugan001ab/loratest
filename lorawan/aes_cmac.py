# lorawan/aes_cmac.py
"""
AES-CMAC (RFC 4493), built on top of MicroPython's ucryptolib AES-ECB block
cipher. This is the primitive LoRaWAN uses for every MIC calculation
(Join-Request, Join-Accept, and data-frame MICs).

ucryptolib is a MicroPython built-in -- no external dependency needed.
"""

import ucryptolib

BLOCK_SIZE = 16
_RB = 0x87  # constant for GF(2^128), per RFC 4493


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _shift_left_1(data: bytes) -> bytes:
    """Left-shift a byte string by 1 bit (used for subkey generation)."""
    out = bytearray(len(data))
    carry = 0
    for i in reversed(range(len(data))):
        out[i] = ((data[i] << 1) | carry) & 0xFF
        carry = 1 if (data[i] & 0x80) else 0
    return bytes(out)


def _aes_ecb_encrypt_block(key: bytes, block: bytes) -> bytes:
    """Encrypt exactly one 16-byte block with AES-128 ECB."""
    cipher = ucryptolib.aes(key, 1)  # 1 = ECB mode
    return cipher.encrypt(block)


def _generate_subkeys(key: bytes):
    """RFC 4493 subkey generation (K1, K2)."""
    zero_block = bytes(BLOCK_SIZE)
    l = _aes_ecb_encrypt_block(key, zero_block)

    if l[0] & 0x80:
        k1 = _xor(_shift_left_1(l), bytes([0] * 15 + [_RB]))
    else:
        k1 = _shift_left_1(l)

    if k1[0] & 0x80:
        k2 = _xor(_shift_left_1(k1), bytes([0] * 15 + [_RB]))
    else:
        k2 = _shift_left_1(k1)

    return k1, k2


def aes_cmac(key: bytes, message: bytes) -> bytes:
    """
    Compute the full 16-byte AES-CMAC tag over `message` using `key`
    (16-byte AES-128 key). LoRaWAN MICs are the first 4 bytes of this tag.
    """
    k1, k2 = _generate_subkeys(key)
    n = (len(message) + BLOCK_SIZE - 1) // BLOCK_SIZE

    if n == 0:
        n = 1
        flag = False
    else:
        flag = (len(message) % BLOCK_SIZE == 0)

    if flag:
        last_block = _xor(message[(n - 1) * BLOCK_SIZE:], k1)
    else:
        remainder = message[(n - 1) * BLOCK_SIZE:]
        padded = remainder + b"\x80" + bytes(BLOCK_SIZE - len(remainder) - 1)
        last_block = _xor(padded, k2)

    x = bytes(BLOCK_SIZE)
    for i in range(n - 1):
        block = message[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]
        x = _aes_ecb_encrypt_block(key, _xor(x, block))

    x = _aes_ecb_encrypt_block(key, _xor(last_block, x))
    return x


def lorawan_mic(key: bytes, message: bytes) -> bytes:
    """Return the 4-byte LoRaWAN MIC (first 4 bytes of the AES-CMAC tag)."""
    return aes_cmac(key, message)[:4]


def aes128_encrypt_block(key: bytes, block16: bytes) -> bytes:
    """Raw single-block AES-128 ECB encrypt, exposed for session-key
    derivation and Join-Accept decryption (both spec'd as raw AES ops)."""
    assert len(block16) == BLOCK_SIZE
    return _aes_ecb_encrypt_block(key, block16)
