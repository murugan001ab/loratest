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
    CMD_SET_MODULATION_PARAMS = 0x8B
    CMD_SET_PACKET_PARAMS = 0x8C
    CMD_SET_BUFFER_BASE_ADDRESS = 0x8F
    CMD_WRITE_BUFFER = 0x0E
    CMD_READ_BUFFER = 0x1E
    CMD_SET_TX = 0x83
    CMD_SET_RX = 0x82
    CMD_SET_DIO_IRQ_PARAMS = 0x08
    CMD_GET_IRQ_STATUS = 0x12
    CMD_CLEAR_IRQ_STATUS = 0x02
    CMD_SET_DIO3_AS_TCXO_CTRL = 0x97
    CMD_CALIBRATE = 0x89
    CMD_GET_STATUS = 0xC0
    CMD_GET_RX_BUFFER_STATUS = 0x13

    # LoRa Sync Word register address (SX126x datasheet 13.4.1)
    REG_LORA_SYNC_WORD_MSB = 0x0740

    # TCXO supply voltage codes (SX126x datasheet 13.1.12)
    TCXO_VOLTAGE = {
        1.6: 0x00,
        1.7: 0x01,
        1.8: 0x02,
        2.2: 0x03,
        2.4: 0x04,
        2.7: 0x05,
        3.0: 0x06,
        3.3: 0x07,
    }

    # LoRa Bandwidth enum (SX126x datasheet 13.4.5.2)
    BW_TABLE = {
        7810:   0x00,
        10420:  0x08,
        15630:  0x01,
        20830:  0x09,
        31250:  0x02,
        41670:  0x0A,
        62500:  0x03,
        125000: 0x04,
        250000: 0x05,
        500000: 0x06,
    }

    # IRQ bit masks (SX126x datasheet 13.3.1)
    IRQ_TX_DONE = 0x0001
    IRQ_RX_DONE = 0x0002
    IRQ_PREAMBLE_DETECTED = 0x0004
    IRQ_SYNC_WORD_VALID = 0x0008
    IRQ_HEADER_VALID = 0x0010
    IRQ_HEADER_ERR = 0x0020
    IRQ_CRC_ERR = 0x0040
    IRQ_TIMEOUT = 0x0200
    IRQ_ALL = 0xFFFF

    XTAL_FREQ = 32000000
    FREQ_STEP = XTAL_FREQ / (1 << 25)  # ~0.9536743164 Hz/LSB

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
        time.sleep_ms(10) # type: ignore
        self.reset_pin.value(1)
        time.sleep_ms(20) # type: ignore
        self.wait_busy()
        self.log.info("Reset complete.")

    def wait_busy(self):
        """Wait until the BUSY pin goes low."""
        timeout = time.ticks_add(time.ticks_ms(), 1000) # type: ignore
        while self.busy_pin.value() == 1:
            if time.ticks_diff(timeout, time.ticks_ms()) < 0: # pyright: ignore[reportAttributeAccessIssue]
                self.log.error("BUSY pin timeout!")
                raise RuntimeError("SX1262 BUSY timeout")
            time.sleep_ms(1) # pyright: ignore[reportAttributeAccessIssue]

    def write_command(self, op_code: int, data: bytes = b''):
        """Write a command to the transceiver."""
        self.wait_busy()
        self.cs.value(0)
        self.spi.write(bytes([op_code]))
        if data:
            self.spi.write(data)
        self.cs.value(1)

    def read_command(self, opcode, length):
        self.wait_busy()

        tx = bytearray([opcode, 0x00] + [0x00] * length)
        rx = bytearray(len(tx))

        self.cs.value(0)
        self.spi.write_readinto(tx, rx)
        self.cs.value(1)

        print("TX:", tx)
        print("RX:", rx)

        return bytes(rx[2:])
    
    CMD_SET_DIO2_AS_RF_SWITCH = 0x9D

    def set_dio2_as_rf_switch(self, enable=True):
        self.write_command(
            self.CMD_SET_DIO2_AS_RF_SWITCH,
            bytes([0x01 if enable else 0x00])
        )

    CMD_SET_REGULATOR_MODE = 0x96

    def set_regulator_mode(self):
        # 0x01 = DC-DC (recommended if available)
        self.write_command(0x96, b"\x01")

    def set_dio3_as_tcxo(self, voltage: float = 1.8, timeout_ms: int = 10):
        """
        Configure DIO3 to supply the TCXO reference voltage and wait for it
        to stabilize before the radio uses it as its clock source.
        Ebyte E22-900M22S modules use an onboard TCXO -- without this the
        PLL calibration/frequency reference can be wrong even though every
        other command appears to succeed.
        NOTE: verify the exact voltage against the E22-900M22S datasheet;
        Ebyte has shipped different TCXO voltages across batches.
        """
        if voltage not in self.TCXO_VOLTAGE:
            raise ValueError(f"Unsupported TCXO voltage: {voltage}")
        voltage_code = self.TCXO_VOLTAGE[voltage]
        timeout_steps = int(timeout_ms * 1000 / 15.625)
        data = bytes([voltage_code]) + bytes([
            (timeout_steps >> 16) & 0xFF,
            (timeout_steps >> 8) & 0xFF,
            timeout_steps & 0xFF,
        ])
        self.write_command(self.CMD_SET_DIO3_AS_TCXO_CTRL, data)
        self.log.info(f"DIO3 configured as TCXO control ({voltage}V)")

    def calibrate_all(self):
        """Run all calibration blocks (RC64k, RC13M, PLL, ADC, IMG). Must be
        done after TCXO is configured / stabilized so the PLL calibrates
        against the correct reference."""
        self.write_command(self.CMD_CALIBRATE, b'\xFF')
        self.wait_busy()
        self.log.info("Calibration complete.")

    def set_sync_word(self, public: bool = True):
        """
        Set the LoRa sync word. LoRaWAN networks (ChirpStack, TTN, etc.)
        use the PUBLIC sync word (0x3444). The SX1262 defaults to the
        PRIVATE sync word (0x1424) on reset -- if this is never set, a
        LoRaWAN gateway will not recognize your packets as valid LoRa
        preambles at all.
        """
        value = b'\x34\x44' if public else b'\x14\x24'
        addr = self.REG_LORA_SYNC_WORD_MSB
        data = bytes([(addr >> 8) & 0xFF, addr & 0xFF]) + value
        self.write_command(self.CMD_WRITE_REGISTER, data)
        self.log.info(f"Sync word set to {'PUBLIC (0x3444)' if public else 'PRIVATE (0x1424)'}")

    def get_status(self):
        """
        Read chip status. The status byte returns on MISO during the
        SECOND byte of the command (opcode, then status while NOP is
        clocked out) -- write_readinto captures it correctly, whereas
        write() + separate read() clocks out and discards the wrong byte.
        """
        self.wait_busy()
        tx = bytes([self.CMD_GET_STATUS, 0x00])
        rx = bytearray(2)
        self.cs.value(0)
        self.spi.write_readinto(tx, rx)
        self.cs.value(1)
        return rx[1]


    def init_lora(self, tcxo_voltage: float = 1.8):
        """Initialize the radio to LoRa mode."""
        self.reset()

        # TCXO must be configured before calibration so the PLL locks
        # against the correct reference. Do this before SetStandby.
        self.set_dio3_as_tcxo(tcxo_voltage)
        self.calibrate_all()

        # Set Standby (RC)
        self.write_command(self.CMD_SET_STANDBY, b'\x00')
        self.log.info(f"Status after reset: {hex(self.get_status())}")

        # Set Packet Type to LoRa (0x01)
        self.write_command(self.CMD_SET_PACKET_TYPE, b'\x01')
        self.set_dio2_as_rf_switch(True)

        # LoRaWAN networks use the public sync word -- without this the
        # gateway won't recognize the packet preamble at all.
        self.set_sync_word(public=True)

        self.log.info("Initialized in LoRa mode.")

    # ------------------------------------------------------------------
    # RF configuration
    # ------------------------------------------------------------------

    def set_rf_frequency(self, freq_hz: int):
        """Set the RF carrier frequency in Hz."""
        freq_reg = int(freq_hz / self.FREQ_STEP)
        data = bytes([
            (freq_reg >> 24) & 0xFF,
            (freq_reg >> 16) & 0xFF,
            (freq_reg >> 8) & 0xFF,
            freq_reg & 0xFF,
        ])
        self.write_command(self.CMD_SET_RF_FREQ, data)
        self.log.info(f"RF frequency set to {freq_hz} Hz")

    def set_modulation_params(self, sf: int, bw_hz: int, cr: int, low_data_rate_optimize=None):
        """
        Configure LoRa modulation.
        sf: spreading factor (7-12)
        bw_hz: bandwidth in Hz (must be a key of BW_TABLE)
        cr: coding rate, 1=4/5, 2=4/6, 3=4/7, 4=4/8
        low_data_rate_optimize: 0/1, auto-enabled for SF11/SF12 @ 125kHz if not given
        """
        if bw_hz not in self.BW_TABLE:
            raise ValueError(f"Unsupported bandwidth: {bw_hz} Hz")
        bw_val = self.BW_TABLE[bw_hz]

        if low_data_rate_optimize is None:
            # LoRaWAN rule of thumb: enable LDRO when symbol time >= 16.38ms
            symbol_time_ms = (1 << sf) / (bw_hz / 1000.0)
            low_data_rate_optimize = 1 if symbol_time_ms >= 16.38 else 0

        data = bytes([sf, bw_val, cr, low_data_rate_optimize])
        self.write_command(self.CMD_SET_MODULATION_PARAMS, data)
        self.log.info(f"Modulation set: SF{sf}, BW{bw_hz}Hz, CR4/{cr+4}, LDRO={low_data_rate_optimize}")

    def set_packet_params(self, payload_len: int, preamble_len: int = 8,
                           header_type: int = 0x00, crc_type: int = 0x01, invert_iq: int = 0x00):
        """
        Configure LoRa packet parameters.
        header_type: 0x00 = explicit header (LoRaWAN uplinks), 0x01 = implicit
        crc_type: 0x00 = off, 0x01 = on
        invert_iq: 0x00 = standard (uplink), 0x01 = inverted (downlink)
        """
        data = bytes([
            (preamble_len >> 8) & 0xFF,
            preamble_len & 0xFF,
            header_type,
            payload_len,
            crc_type,
            invert_iq,
        ])
        self.write_command(self.CMD_SET_PACKET_PARAMS, data)
        self.log.info(f"Packet params set: preamble={preamble_len}, payload_len={payload_len}, "
                      f"header={'implicit' if header_type else 'explicit'}, crc={crc_type}, iq={invert_iq}")

    def set_pa_config(self, pa_duty_cycle: int = 0x04, hp_max: int = 0x07,
                       device_sel: int = 0x00, pa_lut: int = 0x01):
        """
        SX1262 PA config. Defaults are the datasheet-recommended values
        for +22dBm max output on the SX1262 (device_sel=0x00).
        """
        data = bytes([pa_duty_cycle, hp_max, device_sel, pa_lut])
        self.write_command(self.CMD_SET_PA_CONFIG, data)

    def set_tx_params(self, power_dbm: int, ramp_time: int = 0x04):
        """
        Set TX output power and ramp time.
        power_dbm: -17 to +22 dBm (signed byte)
        ramp_time: 0x04 = 200us ramp (common default)
        """
        power_byte = power_dbm & 0xFF  # two's complement encoding for negative values
        data = bytes([power_byte, ramp_time])
        self.write_command(self.CMD_SET_TX_PARAMS, data)
        self.log.info(f"TX power set to {power_dbm} dBm")

    # ------------------------------------------------------------------
    # Buffer / IRQ / TX
    # ------------------------------------------------------------------

    def set_buffer_base_address(self, tx_base: int = 0x00, rx_base: int = 0x00):
        self.write_command(self.CMD_SET_BUFFER_BASE_ADDRESS, bytes([tx_base, rx_base]))

    def write_buffer(self, payload: bytes, offset: int = 0x00):
        """Write the payload into the radio's TX FIFO."""
        self.wait_busy()
        self.cs.value(0)
        self.spi.write(bytes([self.CMD_WRITE_BUFFER, offset]))
        self.spi.write(payload)
        self.cs.value(1)
        self.log.info(f"Wrote {len(payload)} bytes to TX buffer")

    def set_dio_irq_params(self, irq_mask: int, dio1_mask: int, dio2_mask: int = 0x0000, dio3_mask: int = 0x0000):
        data = bytes([
            (irq_mask >> 8) & 0xFF, irq_mask & 0xFF,
            (dio1_mask >> 8) & 0xFF, dio1_mask & 0xFF,
            (dio2_mask >> 8) & 0xFF, dio2_mask & 0xFF,
            (dio3_mask >> 8) & 0xFF, dio3_mask & 0xFF,
        ])
        self.write_command(self.CMD_SET_DIO_IRQ_PARAMS, data)

    def get_irq_status(self):
        raw = self.read_command(self.CMD_GET_IRQ_STATUS, 2)
        print("IRQ RAW:", raw)
        return (raw[0] << 8) | raw[1]
    
    

    def clear_irq_status(self, mask: int = IRQ_ALL):
        data = bytes([(mask >> 8) & 0xFF, mask & 0xFF])
        self.write_command(self.CMD_CLEAR_IRQ_STATUS, data)

    def set_tx(self, timeout_ms: int = 0):
        """
        Start transmission. timeout_ms=0 means no timeout (TX runs until TxDone).
        Timeout unit on the radio is 15.625us steps.
        """

        print("BUSY:", self.busy_pin.value())
        print("DIO1:", self.dio1_pin.value())
        timeout_steps = int(timeout_ms * 1000 / 15.625) if timeout_ms else 0
        data = bytes([
            (timeout_steps >> 16) & 0xFF,
            (timeout_steps >> 8) & 0xFF,
            timeout_steps & 0xFF,
        ])
        self.write_command(self.CMD_SET_TX, data)

    def set_rx(self, timeout_ms: int = 0):
        """
        Start reception. timeout_ms=0 means a single receive with no radio
        timeout (waits indefinitely for RxDone) -- callers should still
        enforce their own wall-clock deadline while polling DIO1.
        Timeout unit on the radio is 15.625us steps.
        """
        timeout_steps = int(timeout_ms * 1000 / 15.625) if timeout_ms else 0
        data = bytes([
            (timeout_steps >> 16) & 0xFF,
            (timeout_steps >> 8) & 0xFF,
            timeout_steps & 0xFF,
        ])
        self.write_command(self.CMD_SET_RX, data)

    def get_rx_buffer_status(self):
        """Returns (payload_length, rx_start_buffer_pointer)."""
        raw = self.read_command(self.CMD_GET_RX_BUFFER_STATUS, 2)
        return raw[0], raw[1]

    def read_buffer(self, offset: int, length: int) -> bytes:
        """Read `length` bytes out of the radio's RX FIFO starting at `offset`."""
        self.wait_busy()
        header = bytes([self.CMD_READ_BUFFER, offset, 0x00])
        tx = header + bytes(length)
        rx = bytearray(len(tx))
        self.cs.value(0)
        self.spi.write_readinto(tx, rx)
        self.cs.value(1)
        return bytes(rx[3:])

    # ------------------------------------------------------------------
    # High-level orchestration
    # ------------------------------------------------------------------

    def transmit(self, payload: bytes, freq_hz: int, sf: int, bw_hz: int, cr: int,
                 power_dbm: int, timeout_ms: int = 4000) -> bool:
        """
        Full LoRa TX chain:
        Standby -> Packet Type -> RF Freq -> Modulation Params -> Packet Params
        -> PA Config -> TX Params -> Buffer Base Addr -> Write Payload -> DIO IRQ -> Set TX
        Blocks (polling DIO1) until TxDone or timeout. Returns True on success.
        """
        self.set_regulator_mode()
        self.write_command(self.CMD_SET_STANDBY, b'\x01')
        self.write_command(self.CMD_SET_PACKET_TYPE, b'\x01')
        self.set_sync_word(public=True)

        self.set_rf_frequency(freq_hz)
        self.set_modulation_params(sf, bw_hz, cr)
        self.set_packet_params(payload_len=len(payload))
        self.set_pa_config()
        self.set_tx_params(power_dbm)

        self.set_buffer_base_address(0x00, 0xFF)
        self.write_buffer(payload)

        # Route TxDone + Timeout IRQs to DIO1 so we can poll it
        self.set_dio_irq_params(
            irq_mask=self.IRQ_TX_DONE | self.IRQ_TIMEOUT,
            dio1_mask=self.IRQ_TX_DONE | self.IRQ_TIMEOUT,
        )
        self.clear_irq_status()

        self.log.info("Starting TX...")
        self.set_tx(timeout_ms)

        deadline = time.ticks_add(time.ticks_ms(), timeout_ms + 500)

        while self.dio1_pin.value() == 0:
            irq = self.get_irq_status()
            self.log.debug(f"BUSY:{self.busy_pin.value()} DIO1:{self.dio1_pin.value()} "
                            f"IRQ:{hex(irq)} STATUS:{hex(self.get_status())}")

            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                self.log.error("TX timed out waiting on DIO1")
                self.clear_irq_status()
                return False

            time.sleep_ms(100)

        status = self.get_irq_status()
        self.clear_irq_status()

        if status & self.IRQ_TX_DONE:
            self.log.info("TX complete (TxDone).")
            return True
        if status & self.IRQ_TIMEOUT:
            self.log.error("TX failed: radio-reported timeout.")
            return False

        self.log.error(f"TX finished with unexpected IRQ status: {status:#06x}")
        return False

    def receive(self, freq_hz: int, sf: int, bw_hz: int, cr: int,
                timeout_ms: int = 3000, max_payload_len: int = 64):
        """
        Open an RX window and wait up to timeout_ms for a downlink packet
        (e.g. a Join-Accept). Returns the received payload bytes, or None
        if the window closed without a valid packet (timeout, CRC error,
        or header error).

        Downlinks are IQ-inverted relative to uplinks -- invert_iq=1 here
        matches what the gateway actually transmits; leaving this at 0
        (the uplink default) means the radio will fail to demodulate a
        Join-Accept even if timing and frequency are correct.
        """
        self.set_regulator_mode()
        self.write_command(self.CMD_SET_STANDBY, b'\x00')
        self.write_command(self.CMD_SET_PACKET_TYPE, b'\x01')
        self.set_sync_word(public=True)

        self.set_rf_frequency(freq_hz)
        self.set_modulation_params(sf, bw_hz, cr)
        # self.set_packet_params(payload_len=max_payload_len, invert_iq=0x01)
        self.set_buffer_base_address(0x00, 0x00)

        self.set_dio_irq_params(
            irq_mask=self.IRQ_RX_DONE | self.IRQ_TIMEOUT | self.IRQ_CRC_ERR | self.IRQ_HEADER_ERR | self.IRQ_PREAMBLE_DETECTED,
            dio1_mask=self.IRQ_RX_DONE | self.IRQ_TIMEOUT | self.IRQ_CRC_ERR | self.IRQ_HEADER_ERR,
        )
        self.clear_irq_status()

        self.set_packet_params(
            payload_len=max_payload_len,
            invert_iq=0x01
            )

        self.log.info(f"Opening RX window ({timeout_ms}ms)...")
        self.set_rx(timeout_ms)

        deadline = time.ticks_add(time.ticks_ms(), timeout_ms + 500)
        while self.dio1_pin.value() == 0:
            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                self.log.info("RX window closed: no DIO1 activity (nothing received).")
                self.clear_irq_status()
                return None
            time.sleep_ms(20)

        status = self.get_irq_status()
        self.clear_irq_status()

        if status & (self.IRQ_CRC_ERR | self.IRQ_HEADER_ERR):
            self.log.error(f"RX failed: CRC/header error (IRQ={status:#06x}).")
            return None
        if not (status & self.IRQ_RX_DONE):
            if status & self.IRQ_PREAMBLE_DETECTED:
                # Radio saw RF energy shaped like a LoRa preamble but never
                # locked sync/header -- points at a parameter mismatch
                # (freq/SF/BW/IQ) rather than "nothing arrived".
                self.log.info(f"RX timed out, but a preamble WAS detected (IRQ={status:#06x}) "
                              f"-- signal is arriving, check SF/BW/IQ/sync-word match.")
            else:
                # No PreambleDetected bit at all -- the chip never saw
                # anything resembling RF energy during the window.
                self.log.info(f"RX window closed without RxDone (IRQ={status:#06x}), "
                              f"no preamble ever detected -- likely nothing reached the antenna.")
            return None

        payload_len, start_ptr = self.get_rx_buffer_status()
        data = self.read_buffer(start_ptr, payload_len)
        self.log.info(f"Received {len(data)} bytes.")
        return data
