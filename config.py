# config.py

CONFIG = {
   # Device Credentials (MSB format for ChirpStack)
    "DEV_EUI": b"\x70\xb3\xd5\x7e\xd0\x05\x12\x34",
    "JOIN_EUI": b"\x54\xc6\x4b\xa4\x28\xb1\x99\x34",
    "APP_KEY": b"\x03\x44\xf3\xc4\xf7\xeb\x4c\x02\x72\x8f\xd2\xb2\xb9\x00\x86\xf5",
    
    # Device Info
    "DEVICE_NAME": "ESP32_E22_Node_1",
    
    # Safe Hardware Pins for ESP8266
    "PIN_SCK": 14,   # D5
    "PIN_MOSI": 13,  # D7
    "PIN_MISO": 12,  # D6
    "PIN_CS": 5,     # D1
    "PIN_RESET": 4,  # D2
    "PIN_BUSY": 16,  # D0
    "PIN_DIO1": 15,  # D8
    # "PIN_RXEN": 1,   # TX Pin
    # "PIN_TXEN": 3,   # RX Pin
    "PIN_LED": 2,    # Onboard LED
    
    # LoRaWAN / Region Settings (IN865)
    "REGION": "IN865",
    "TX_POWER": 14,          # dBm
    "SPREADING_FACTOR": 7,   # SF7
    "BANDWIDTH": 125000,     # 125 kHz
    "CODING_RATE": 5,        # CR 4/5
    "SYNC_WORD": 0x3444,     # Public LoRaWAN Sync Word
    "RX1_DELAY": 1000,       # ms (ChirpStack default is often 1s)
    
    # Application settings
    "TX_INTERVAL": 30        # seconds
}