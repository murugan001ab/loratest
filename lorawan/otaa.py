# lorawan/otaa.py
"""
LoRaWAN 1.0.x OTAA join logic: builds the Join-Request PHYPayload,
decrypts and validates a received Join-Accept, and derives NwkSKey/AppSKey.

Byte-order note (per config.py's convention):
  CONFIG["DEV_EUI"] / CONFIG["JOIN_EUI"] / CONFIG["APP_KEY"] are stored in
  MSB / "display" order, exactly as ChirpStack shows them. On the wire,
  LoRaWAN EUIs and nonces are sent little-endian-first; AppKey itself is
  used as-is (it's not byte-reversed). This module does all the reversing
  so nothing above it has to think about wire byte order.
"""

from struct import pack
from .aes_cmac import lorawan_mic, aes128_encrypt_block

MHDR_JOIN_REQUEST = 0x00
MHDR_JOIN_ACCEPT = 0x20

_DEVNONCE_FILE = "devnonce.dat"


def _reversed(b: bytes) -> bytes:
    return bytes(reversed(b))


def _load_dev_nonce() -> int:
    """
    DevNonce must not repeat for a given JoinEUI/DevEUI pair (LoRaWAN 1.0.x
    servers reject replayed/non-increasing nonces), so it's persisted to
    flash and incremented across reboots rather than reset to 0 every boot.
    """
    try:
        with open(_DEVNONCE_FILE, "r") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def _save_dev_nonce(value: int):
    with open(_DEVNONCE_FILE, "w") as f:
        f.write(str(value))


def next_dev_nonce() -> int:
    """Read, increment, persist, and return the next DevNonce to use."""
    nonce = (_load_dev_nonce() + 1) & 0xFFFF
    _save_dev_nonce(nonce)
    return nonce


def build_join_request(config: dict, dev_nonce: int) -> bytes:
    """
    Build the full Join-Request PHYPayload:
        MHDR(1) | JoinEUI(8,LE) | DevEUI(8,LE) | DevNonce(2,LE) | MIC(4)
    MIC = AES-CMAC(AppKey, MHDR|JoinEUI|DevEUI|DevNonce)[0:4]
    """
    mhdr = bytes([MHDR_JOIN_REQUEST])
    join_eui_le = _reversed(config["JOIN_EUI"])
    dev_eui_le = _reversed(config["DEV_EUI"])
    dev_nonce_le = pack("<H", dev_nonce)

    payload = mhdr + join_eui_le + dev_eui_le + dev_nonce_le
    mic = lorawan_mic(config["APP_KEY"], payload)

    return payload + mic


class JoinAccept:
    def __init__(self, app_nonce: bytes, net_id: bytes, dev_addr: bytes,
                 dl_settings: int, rx_delay: int, cf_list: bytes = b""):
        self.app_nonce = app_nonce      # 3 bytes, wire order (LE)
        self.net_id = net_id            # 3 bytes, wire order (LE)
        self.dev_addr = dev_addr        # 4 bytes, wire order (LE)
        self.dl_settings = dl_settings
        self.rx_delay = rx_delay
        self.cf_list = cf_list


def parse_join_accept(config: dict, phy_payload: bytes):
    """
    Decrypt + validate a received Join-Accept PHYPayload.

    Per LoRaWAN spec, the server encrypts the Join-Accept using an AES
    *decrypt* operation, so the device recovers the plaintext by running
    the AES *encrypt* operation over the ciphertext blocks (ECB, ciphertext
    is always a multiple of 16 bytes: 16 without CFList, 32 with).

    Returns a JoinAccept object on success, or None if the MIC is invalid
    or the frame is malformed.
    """
    if len(phy_payload) < 1:
        return None

    mhdr = phy_payload[0]
    if mhdr != MHDR_JOIN_ACCEPT:
        return None

    ciphertext = phy_payload[1:]
    if len(ciphertext) not in (16, 32):
        return None

    app_key = config["APP_KEY"]
    plaintext = b"".join(
        aes128_encrypt_block(app_key, ciphertext[i:i + 16])
        for i in range(0, len(ciphertext), 16)
    )

    body = plaintext[:-4]
    received_mic = plaintext[-4:]
    expected_mic = lorawan_mic(app_key, bytes([mhdr]) + body)

    if expected_mic != received_mic:
        return None

    app_nonce = body[0:3]
    net_id = body[3:6]
    dev_addr = body[6:10]
    dl_settings = body[10]
    rx_delay = body[11]
    cf_list = body[12:] if len(body) > 12 else b""

    return JoinAccept(app_nonce, net_id, dev_addr, dl_settings, rx_delay, cf_list)


def derive_session_keys(config: dict, join_accept: "JoinAccept", dev_nonce: int):
    """
    LoRaWAN 1.0.x session key derivation:
        NwkSKey = aes128_encrypt(AppKey, 0x01 | AppNonce | NetID | DevNonce | pad16)
        AppSKey = aes128_encrypt(AppKey, 0x02 | AppNonce | NetID | DevNonce | pad16)
    AppNonce/NetID are used exactly as received (wire/LE order); DevNonce is
    the same little-endian 2-byte value that was sent in the Join-Request.
    """
    app_key = config["APP_KEY"]
    dev_nonce_le = pack("<H", dev_nonce)

    def block(prefix: int) -> bytes:
        b = bytes([prefix]) + join_accept.app_nonce + join_accept.net_id + dev_nonce_le
        return b + bytes(16 - len(b))  # zero-pad to 16 bytes

    nwk_skey = aes128_encrypt_block(app_key, block(0x01))
    app_skey = aes128_encrypt_block(app_key, block(0x02))
    return nwk_skey, app_skey
