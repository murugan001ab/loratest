# main.py
import asyncio as asyncio
import json
import time
from machine import Pin, SPI
from config import CONFIG
from drivers.sx1262 import SX1262
from utils.logger import Logger
from lorawan.otaa import (
    next_dev_nonce,
    build_join_request,
    parse_join_accept,
    derive_session_keys,
)

log = Logger("MAIN")

# Hardware Initialization
led = Pin(CONFIG["PIN_LED"], Pin.OUT)
led.value(1) # Active-low on most ESP8266 boards (1 = Off)

spi = SPI(
    2,
    baudrate=1000000,
    polarity=0,
    phase=0,
    bits=8,
    firstbit=SPI.MSB,
    sck=Pin(18),
    mosi=Pin(23),
    miso=Pin(19),
)
cs = Pin(CONFIG["PIN_CS"], Pin.OUT)
reset = Pin(CONFIG["PIN_RESET"], Pin.OUT)
busy = Pin(CONFIG["PIN_BUSY"], Pin.IN)
dio1 = Pin(CONFIG["PIN_DIO1"], Pin.IN)

# RF Switch Pins for Ebyte E22 (Overriding TX/RX pin functions)
print("dio pin",dio1)

radio = SX1262(spi, cs, reset, busy, dio1)

async def blink_led(duration_ms: int = 200):
    """Blinks the onboard LED to indicate activity."""
    led.value(0) # LED On
    await asyncio.sleep_ms(duration_ms) # type: ignore
    led.value(1) # LED Off


# Populated once a Join Accept is validated; used by the (future) uplink
# MAC layer to encrypt payloads / compute data-frame MICs.
NWK_SKEY = None
APP_SKEY = None
DEV_ADDR = None


async def join_network() -> bool:
    """Performs a real LoRaWAN OTAA Join: builds and transmits a signed
    Join-Request, then listens in RX1 (and RX2 if needed) for a Join-Accept.
    Retries indefinitely on failure/timeout."""
    global NWK_SKEY, APP_SKEY, DEV_ADDR

    log.info(f"Attempting OTAA Join on {CONFIG['REGION']}...")

    tx_sf, tx_bw_hz = CONFIG["DR_TABLE"][CONFIG["DEFAULT_DR"]]
    rx2_sf, rx2_bw_hz = CONFIG["DR_TABLE"][CONFIG["RX2_DR"]]

    while True:
        await blink_led(100)

        dev_nonce = next_dev_nonce()
        join_request = build_join_request(CONFIG, dev_nonce)
        tx_freq = CONFIG["TX_CHANNELS_HZ"][dev_nonce % len(CONFIG["TX_CHANNELS_HZ"])]

        log.info(f"Sending Join Request (DevNonce={dev_nonce}) on {tx_freq} Hz...")
        sent = radio.transmit(
            payload=join_request,
            freq_hz=tx_freq,
            sf=tx_sf,
            bw_hz=tx_bw_hz,
            cr=CONFIG["CODING_RATE"],
            power_dbm=CONFIG["TX_POWER"],
        )
        if not sent:
            log.error("Join Request transmit failed, retrying...")
            await asyncio.sleep(CONFIG["JOIN_RETRY_DELAY"])
            continue

        # RX1: same frequency/datarate as the uplink. Join-Accept RX1 opens
        # JOIN_ACCEPT_DELAY1_MS after the end of TX -- this is a fixed
        # LoRaWAN-spec delay for OTAA (5s), distinct from the 1s RX1_DELAY_MS
        # used for ordinary Class-A data-frame replies. The window itself
        # must stay short: JOIN_ACCEPT_DELAY2_MS - JOIN_ACCEPT_DELAY1_MS is
        # only 1000ms here, so a long RX1 window would overrun straight
        # through RX2's correct opening time.
        RX_WINDOW_MS = 600
        await asyncio.sleep_ms(CONFIG["JOIN_ACCEPT_DELAY1_MS"])
        log.info("Listening in RX1 window for Join Accept...")
        raw = radio.receive(
            freq_hz=tx_freq, sf=tx_sf, bw_hz=tx_bw_hz, cr=CONFIG["CODING_RATE"],
            timeout_ms=RX_WINDOW_MS, max_payload_len=33,
        )

        if raw is None:
            # RX2: fixed frequency/datarate. Join-Accept RX2 opens
            # JOIN_ACCEPT_DELAY2_MS after TX end (6s) -- sleep only the
            # remaining gap since RX1 already consumed part of it.
            elapsed_ms = CONFIG["JOIN_ACCEPT_DELAY1_MS"] + RX_WINDOW_MS
            remaining_ms = CONFIG["JOIN_ACCEPT_DELAY2_MS"] - elapsed_ms
            if remaining_ms > 0:
                await asyncio.sleep_ms(remaining_ms)
            log.info("Listening in RX2 window for Join Accept...")
            raw = radio.receive(
                freq_hz=CONFIG["RX2_FREQ_HZ"], sf=rx2_sf, bw_hz=rx2_bw_hz,
                cr=CONFIG["CODING_RATE"], timeout_ms=RX_WINDOW_MS + 1000, max_payload_len=33,
            )

        if raw is not None:
            join_accept = parse_join_accept(CONFIG, raw)
            if join_accept is not None:
                NWK_SKEY, APP_SKEY = derive_session_keys(CONFIG, join_accept, dev_nonce)
                DEV_ADDR = join_accept.dev_addr
                log.info(f"Join Accept received. DevAddr={DEV_ADDR.hex()}")
                return True
            log.error("Received a downlink but it failed Join-Accept MIC validation.")
        else:
            log.error("No Join Accept received in RX1 or RX2.")

        log.info(f"Retrying join in {CONFIG['JOIN_RETRY_DELAY']}s...")
        await asyncio.sleep(CONFIG["JOIN_RETRY_DELAY"])

def get_sensor_data() -> str:
    """Mock function to read sensors and format as JSON."""
    data = {
        "temperature": 25.4,
        "humidity": 62.1,
        "voltage": 3.74
    }
    return json.dumps(data)

async def uplink_task():
    """Handles the periodic 30-second uplink transmission loop."""
    while True:
        payload = get_sensor_data().encode()

        success = radio.transmit(
            payload=payload,
            freq_hz=865062500,
            sf=7,
            bw_hz=125000,
            cr=1,
            power_dbm=22,
        )

        if success:
            log.info("Packet transmitted")
        else:
            log.error("Transmission failed")
        
        await asyncio.sleep(CONFIG["TX_INTERVAL"])


async def main():
    log.info("Booting ESP32 Node...")
    radio.init_lora()
    
    # Block until network connection status clears
    await join_network()
    
    # Start the continuous background uplink loop
    asyncio.create_task(uplink_task())
    
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Application stopped manually.")
    except Exception as e:
        log.error(f"Fatal Error: {e}")