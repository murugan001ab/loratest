from machine import Pin, SPI
import time

# --- Hardware Configuration Pins ---
PIN_RST = 27
PIN_CS = 5
PIN_BUSY = 25
PIN_SCK = 18
PIN_MOSI = 23
PIN_MISO = 19

# Initialize control GPIOs
rst = Pin(PIN_RST, Pin.OUT)
cs = Pin(PIN_CS, Pin.OUT)
busy = Pin(PIN_BUSY, Pin.IN)

# Ensure CS starts high (de-selected)
cs.value(1)

# Initialize SPI Bus (Mode 0: polarity=0, phase=0)
spi = SPI(
    2,
    baudrate=1000000,
    polarity=0,
    phase=0,
    sck=Pin(PIN_SCK),
    mosi=Pin(PIN_MOSI),
    miso=Pin(PIN_MISO)
)

# --- Helper Functions ---

def wait_on_busy():
    """Blocks execution until the SX1262 finishes processing and drops BUSY low."""
    # Add a tiny delay to give the chip a microsecond to pull BUSY high if a command just completed
    time.sleep_us(10) 
    while busy.value() == 1:
        pass

def write_cmd(opcode, data_bytes=None):
    """Writes a command opcode followed by optional data array parameters."""
    wait_on_busy()
    cs.value(0)
    
    # Send Command Opcode
    spi.write(bytearray([opcode]))
    
    # Send parameters if they exist
    if data_bytes:
        spi.write(bytearray(data_bytes))
        
    cs.value(1)
    wait_on_busy() # Wait for the chip to settle after execution

def read_cmd(opcode, num_bytes_to_read):
    """Sends an opcode followed by a status dummy byte, then reads back values."""
    wait_on_busy()
    cs.value(0)
    
    spi.write(bytearray([opcode, 0x00])) # Opcode + NOP status tracking byte
    rx_buf = bytearray(num_bytes_to_read)
    spi.readinto(rx_buf)
    
    cs.value(1)
    wait_on_busy()
    return rx_buf

# --- Step-by-Step Task Functions ---

def reset_radio():
    print("Resetting SX1262...")
    rst.value(0)
    time.sleep_ms(20)
    rst.value(1)
    time.sleep_ms(20)
    print("-> Hardware Reset Complete")

def get_status():
    # Opcode 0xC0: GetStatus
    res = read_cmd(0xC0, 1)
    status_val = res[0]
    
    # Extract structural info out of the status byte
    chip_mode = (status_val >> 4) & 0x07
    cmd_status = (status_val >> 1) & 0x07
    
    print(f"-> Chip Status Byte: {hex(status_val)} (Mode: {chip_mode}, CmdStatus: {cmd_status})")
    return status_val

def set_standby():
    print("Setting Standby Mode (RC 13MHz)...")
    # Opcode 0x80, parameter 0x01 for STDBY_RC
    write_cmd(0x80, [0x01])

def set_packet_type_lora():
    print("Setting Packet Type to LoRa...")
    # Opcode 0x8A, parameter 0x01 (0x01 = LoRa, 0x00 = FSK)
    write_cmd(0x8A, [0x01])

def configure_modulation():
    print("Configuring LoRa Modulation Params...")
    # Opcode 0x8B: SetModulationParams
    # Parameters: SF7 (0x07), BW125kHz (0x04), CR4/5 (0x01), LowDataRateOptimize Off (0x00)
    write_cmd(0x8B, [0x07, 0x04, 0x01, 0x00])

def configure_packet_params(payload_len):
    print(f"Configuring Packet Params (Length: {payload_len} bytes)...")
    # Opcode 0x8C: SetPacketParams
    # Params: Preamble MSB(0x00), Preamble LSB(0x08), Explicit Header(0x00), 
    # Payload Length, CRC On(0x01), Standard IQ(0x00)
    write_cmd(0x8C, [0x00, 0x08, 0x00, payload_len, 0x01, 0x00])

def set_rf_frequency():
    print("Configuring RF Frequency to 915 MHz...")
    # Opcode 0x86: SetRfFrequency
    # Formula: F_rf = F_xtal (32MHz) / 2^25 * RF_FREQ_REG_VAL
    # 915,000,000 Hz / (32,000,000 / 33,554,432) = 959,447,040 = 0x39300000
    write_cmd(0x86, [0x39, 0x30, 0x00, 0x00])

def write_payload(msg):
    print(f"Writing payload data: '{msg}'")
    payload_bytes = msg.encode('utf-8')
    payload_len = len(payload_bytes)
    
    # 1. Map RAM buffer entry pointers: Opcode 0x8F (SetBufferBaseAddress)
    # TX Base address = 0x00, RX Base address = 0x00
    write_cmd(0x8F, [0x00, 0x00])
    
    # 2. Write data to buffer: Opcode 0x0E (WriteBuffer)
    # Argument 1: Offset address (0x00)
    # Arguments 2+: The data byte payload stream
    data_to_send = [0x00] + list(payload_bytes)
    write_cmd(0x0E, data_to_send)
    
    return payload_len

def start_tx():
    print("Triggering Transmission (TX Mode)...")
    # Opcode 0x83: SetTx
    # Timeout 0x000000 = No timeout (single transmission mode)
    write_cmd(0x83, [0x00, 0x00, 0x00])
    print("-> Radio is transmitting!")


# --- Execution Pipeline ---
def main():
    print("=== Starting SX1262 Functional Test ===")
    
    # 1. Reset chip state
    reset_radio()
    
    # 2. Verify SPI bus connectivity
    get_status()
    
    # 3. Enter Configuration State
    set_standby()
    set_packet_type_lora()
    
    # 4. Define RF & Modulator parameters
    set_rf_frequency()
    configure_modulation()
    
    # 5. Pack data payload and size headers
    message_str = "Hello"
    length = write_payload(message_str)
    configure_packet_params(length)
    
    # 6. Push payload to airwaves
    start_tx()
    
    print("=== Test Sequence Finalized ===")

if __name__ == "__main__":
    main()