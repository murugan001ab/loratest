from struct import pack

# LoRaWAN Join Request
# MHDR | JoinEUI | DevEUI | DevNonce | MIC

MHDR = bytes([0x00])  # Join Request

JoinEUI = bytes.fromhex("0102030405060708")[::-1]
DevEUI  = bytes.fromhex("1122334455667788")[::-1]
DevNonce = pack("<H", 1)

payload = MHDR + JoinEUI + DevEUI + DevNonce

# Normally you would calculate the MIC here.
# Instead, deliberately make it invalid.
bad_mic = b"\x00\x00\x00\x00"

phy_payload = payload + bad_mic

print(phy_payload.hex())