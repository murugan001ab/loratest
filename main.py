# main.py
import asyncio as asyncio
import json
import time
from machine import Pin, SPI
from config import CONFIG
from drivers.sx1262 import SX1262
from utils.logger import Logger

log = Logger("MAIN")

# Hardware Initialization
led = Pin(CONFIG["PIN_LED"], Pin.OUT)
led.value(1) # Active-low on most ESP8266 boards (1 = Off)

# ESP8266 Hardware SPI 1 maps to SCK(D5), MISO(D6), MOSI(D7)
spi = SPI(1, baudrate=2000000, polarity=0, phase=0)

cs = Pin(CONFIG["PIN_CS"], Pin.OUT)
reset = Pin(CONFIG["PIN_RESET"], Pin.OUT)
busy = Pin(CONFIG["PIN_BUSY"], Pin.IN)
dio1 = Pin(CONFIG["PIN_DIO1"], Pin.IN)

# RF Switch Pins for Ebyte E22 (Overriding TX/RX pin functions)


radio = SX1262(spi, cs, reset, busy, dio1)

async def blink_led(duration_ms: int = 200):
    """Blinks the onboard LED to indicate activity."""
    led.value(0) # LED On
    await asyncio.sleep_ms(duration_ms) # type: ignore
    led.value(1) # LED Off


async def join_network() -> bool:
    """Attempts OTAA Join simulation with RF switch switching."""
    log.info(f"Attempting OTAA Join on {CONFIG['REGION']}...")
    joined = False
    
    while not joined:
        await blink_led(100)
        log.info("Flipping RF switch to TX...")
        
        log.info("Sending Join Request...")
        await asyncio.sleep_ms(150) # type: ignore # Simulate transmission time
        
        log.info("Flipping RF switch to RX (Listening for Join Accept)...")
        
        await asyncio.sleep(5) # Wait for RX1 / RX2 window timeouts
        
        joined = True 
        log.info("Successfully joined ChirpStack network!")
        
    return joined

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
        payload = get_sensor_data()
        log.info(f"Preparing uplink: {payload}")
        
        await blink_led(50)
        
        log.info("TX complete. Opening RX windows...")
        
        await asyncio.sleep(2) # Open through both RX1 and RX2 timing delays
        
        log.info("RX windows closed. Entering sleep cycle.")
        
        await asyncio.sleep(CONFIG["TX_INTERVAL"])

async def main():
    log.info("Booting ESP8266 Node...")
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