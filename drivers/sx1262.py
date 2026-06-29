# drivers/sx1262.py
import time
from machine import Pin, SPI
from utils.logger import Logger

class SX1262:
    # SX1262 Opcodes
    CMD_SET_STANDBY = 0x80
    CMD_SET_PACKET_TYPE = 0x8A
    CMD_SET_RF_FREQ = 0x86
    CMD_SET_PA_CONFIG = 0x95
    CMD_SET_TX_PARAMS = 0x8E
    CMD_WRITE_REGISTER = 0x0D
    CMD_READ_REGISTER = 0x1D

    def __init__(self, spi: SPI, cs: Pin, reset: Pin, busy: Pin, dio1: Pin):
        self.log = Logger("SX1262")
        self.spi = spi
        self.cs = cs
        self.reset_pin = reset
        self.busy_pin = busy
        self.dio1_pin = dio1
        
        self.cs.value(1)
        
    def reset(self):
        """Hardware reset of the SX1262."""
        self.log.info("Resetting transceiver...")
        self.reset_pin.value(0)
        time.sleep_ms(10)
        self.reset_pin.value(1)
        time.sleep_ms(20)
        self.wait_busy()
        self.log.info("Reset complete.")

    def wait_busy(self):
        """Wait until the BUSY pin goes low."""
        timeout = time.ticks_add(time.ticks_ms(), 1000)
        while self.busy_pin.value() == 1:
            if time.ticks_diff(timeout, time.ticks_ms()) < 0:
                self.log.error("BUSY pin timeout!")
                raise RuntimeError("SX1262 BUSY timeout")
            time.sleep_ms(1)

    def write_command(self, op_code: int, data: bytes = b''):
        """Write a command to the transceiver."""
        self.wait_busy()
        self.cs.value(0)
        self.spi.write(bytes([op_code]))
        if data:
            self.spi.write(data)
        self.cs.value(1)

    def read_command(self, op_code: int, length: int) -> bytes:
        """Read data from the transceiver."""
        self.wait_busy()
        self.cs.value(0)
        self.spi.write(bytes([op_code, 0x00])) # Send opcode + NOP
        data = self.spi.read(length)
        self.cs.value(1)
        return data

    def init_lora(self):
        """Initialize the radio to LoRa mode."""
        self.reset()
        # Set Standby (RC)
        self.write_command(self.CMD_SET_STANDBY, b'\x00')
        # Set Packet Type to LoRa (0x01)
        self.write_command(self.CMD_SET_PACKET_TYPE, b'\x01')
        self.log.info("Initialized in LoRa mode.")