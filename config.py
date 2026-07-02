# config.py
"""
Central configuration for the ESP8266 + SX1262 (Ebyte E22 SPI) LoRaWAN OTAA node.
All keys/EUIs are stored in the "display" byte order (the same order ChirpStack
shows them in the UI, MSB-first). The LoRaWAN stack (lorawan/lorawan.py) is
responsible for reversing them to little-endian on the wire where required.
"""

CONFIG = {
    # ---- Device Credentials (MSB / display order, as copied from ChirpStack) ----
    "DEV_EUI":  b"\x70\xb3\xd5\x7e\xd0\x05\x12\x34",
    "JOIN_EUI": b"\x54\xc6\x4b\xa4\x28\xb1\x99\x34",
    "APP_KEY":  b"\x03\x44\xf3\xc4\xf7\xeb\x4c\x02\x72\x8f\xd2\xb2\xb9\x00\x86\xf5",

    # ---- Device Info ----
    "DEVICE_NAME": "ESP8266_E22_Node_1",

    # ---- Hardware Pins (ESP8266 NodeMCU) ----
    # NOTE: GPIO1 (TX) and GPIO3 (RX) are intentionally never used here.
    "PIN_SCK":   18,  # D5 - HSPI SCK  (fixed by hardware SPI(1))
    "PIN_MOSI":  23,  # D7 - HSPI MOSI (fixed by hardware SPI(1))
    "PIN_MISO":  19,  # D6 - HSPI MISO (fixed by hardware SPI(1))
    "PIN_CS":     5,  # D1 - NSS (software-controlled chip select)
    "PIN_RESET":  27,  # D2 - RESET (active low)
    "PIN_BUSY":  25,  
    "PIN_DIO1":  26,  
    "PIN_LED"  :2,

    # ---- LoRaWAN / Region Settings (IN865, ChirpStack) ----
    "REGION": "IN865",

    # IN865 fixed uplink channel plan (Hz). ChirpStack's IN865 region default.
    "TX_CHANNELS_HZ": [
        865062500,
        865402500,
        865985000,
    ],
    "RX2_FREQ_HZ": 866550000,
    "RX2_DR": 2,              # IN865 RX2 default: DR10 = SF7/BW125 in ChirpStack's table mapping below

    # Datarate table for IN865 (index -> (SF, BW_Hz))
    "DR_TABLE": {
        0:  (12, 125000),
        1:  (11, 125000),
        2:  (10, 125000),
        3:  (9,  125000),
        4:  (8,  125000),
        5:  (7,  125000),
        10: (7,  125000),  # Used here purely as the RX2 datarate alias
    },

    "DEFAULT_DR": 5,           # SF7BW125 for uplinks
    "TX_POWER": 14,            # dBm
    "CODING_RATE": 1,          # SX1262 LoRaWAN value: 1 = 4/5
    "SYNC_WORD_PUBLIC": True,  # LoRaWAN public network sync word (0x3444)

    "RX1_DELAY_MS": 5000,
    "RX2_DELAY_MS": 6000,
    "JOIN_ACCEPT_DELAY1_MS": 5000,
    "JOIN_ACCEPT_DELAY2_MS": 6000,

    "MAX_FCNT_GAP": 16384,

    # ---- Application settings ----
    "TX_INTERVAL": 30,        # seconds between uplinks
    "JOIN_RETRY_DELAY": 10,   # seconds between failed join attempts
}
