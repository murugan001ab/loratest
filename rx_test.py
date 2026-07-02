import machine
import time
import struct
import ubinascii
import ucryptolib

# ============================================================================
# LORAWAN CREDENTIALS (HEX STRINGS - EDIT THESE)
# ============================================================================
DEV_EUI_HEX  = "70b3d57ed0051234"
JOIN_EUI_HEX = "eef65f211d98e0ba"
APP_KEY_HEX  = "4244f24b0bcb1a7b8b4210a2884b4049"

# ============================================================================
# HARDWARE CONFIGURATION
# ============================================================================
SCK_PIN   = 18
MOSI_PIN  = 23
MISO_PIN  = 19
NSS_PIN   = 5
RESET_PIN = 27
BUSY_PIN  = 25
DIO1_PIN  = 26

# ============================================================================
# IN865 REGIONAL CONSTANTS
# ============================================================================
UPLINK_CHANNELS = [865062500, 865402500, 865985000]
RX2_FREQ        = 866550000
RX2_SF          = 10   # SF7
RX2_BW          = 4   # SX1262 BW 125kHz index = 4

# LoRa Modulation Settings for Join Request
TX_SF           = 7
TX_BW           = 4    # 125 kHz
TX_CR           = 1    # 4/5
TX_PREAMBLE     = 8

JOIN_TIMEOUT_RX1_MS = 5000
JOIN_TIMEOUT_RX2_MS = 6000

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def reverse_bytes(b):
    res = bytearray(len(b))
    for i in range(len(b)):
        res[i] = b[len(b) - 1 - i]
    return bytes(res)

# ============================================================================
# CRYPTO PRIMITIVES (Pure Python CMAC over MicroPython AES-ECB)
# ============================================================================
def aes_128_ecb_encrypt(key, data):
    cipher = ucryptolib.aes(key, 1) # 1 = ECB mode encrypt
    return cipher.encrypt(data)

def xor_bytes(b1, b2):
    return bytes(a ^ b for a, b in zip(b1, b2))

def shift_left_one_bit(b):
    out = bytearray(len(b))
    carry = 0
    for i in range(len(b) - 1, -1, -1):
        out[i] = ((b[i] << 1) | carry) & 0xFF
        carry = 1 if (b[i] & 0x80) else 0
    return bytes(out), carry

def generate_subkeys(key):
    zero_block = b'\x00' * 16
    L = aes_128_ecb_encrypt(key, zero_block)
    
    K1, carry = shift_left_one_bit(L)
    if carry:
        K1 = xor_bytes(K1, b'\x00' * 15 + b'\x87')
        
    K2, carry = shift_left_one_bit(K1)
    if carry:
        K2 = xor_bytes(K2, b'\x00' * 15 + b'\x87')
    return K1, K2

def aes_cmac(key, msg):
    K1, K2 = generate_subkeys(key)
    const_Bsize = 16
    n = len(msg) // const_Bsize
    remainder = len(msg) % const_Bsize
    
    if remainder != 0 or n == 0:
        n += 1
        flag = False
    else:
        flag = True
        
    M = [msg[i*16:(i+1)*16] for i in range(len(msg)//16 + (1 if remainder else 0))]
    
    if flag:
        M[-1] = xor_bytes(M[-1], K1)
    else:
        padding = b'\x80' + b'\x00' * (const_Bsize - remainder - 1)
        M[-1] = xor_bytes(M[-1] + padding, K2)
        
    X = b'\x00' * 16
    for i in range(n):
        Y = xor_bytes(X, M[i])
        X = aes_128_ecb_encrypt(key, Y)
    return X

# ============================================================================
# SX1262 SPI & COMMAND DRIVER
# ============================================================================
class SX1262:
    def __init__(self):
        self.nss = machine.Pin(NSS_PIN, machine.Pin.OUT, value=1)
        self.busy = machine.Pin(BUSY_PIN, machine.Pin.IN)
        self.reset = machine.Pin(RESET_PIN, machine.Pin.OUT, value=1)
        self.spi = machine.SPI(1, baudrate=2000000, polarity=0, phase=0,
                               sck=machine.Pin(SCK_PIN),
                               mosi=machine.Pin(MOSI_PIN),
                               miso=machine.Pin(MISO_PIN))
        self.dio1 = machine.Pin(DIO1_PIN, machine.Pin.IN)

    def wait_busy(self):
        while self.busy.value() == 1:
            time.sleep_us(10)

    def hw_reset(self):
        print("[SX1262] Executing Hardware Reset...")
        self.reset.value(0)
        time.sleep_ms(20)
        self.reset.value(1)
        time.sleep_ms(20)
        self.wait_busy()

    def write_cmd(self, opcode, data=b''):
        self.wait_busy()
        self.nss.value(0)
        self.spi.write(bytes([opcode]))
        if data:
            self.spi.write(data)
        self.nss.value(1)

    def read_cmd(self, opcode, dummy_bytes=1, r_len=1):
        self.wait_busy()
        self.nss.value(0)
        self.spi.write(bytes([opcode]))
        if dummy_bytes > 0:
            self.spi.write(b'\x00' * dummy_bytes)
        res = self.spi.read(r_len)
        self.nss.value(1)
        return res

    def write_reg(self, reg, data):
        self.wait_busy()
        self.nss.value(0)
        self.spi.write(struct.pack(">BH", 0x0D, reg))
        self.spi.write(data)
        self.nss.value(1)

    def read_reg(self, reg, length=1):
        self.wait_busy()
        self.nss.value(0)
        self.spi.write(struct.pack(">BH", 0x1D, reg))
        self.spi.write(b'\x00') # Dummy byte
        res = self.spi.read(length)
        self.nss.value(1)
        return res

    def write_buffer(self, offset, data):
        self.wait_busy()
        self.nss.value(0)
        self.spi.write(bytes([0x0E, offset]))
        self.spi.write(data)
        self.nss.value(1)

    def read_buffer(self, offset, length):
        self.wait_busy()
        self.nss.value(0)
        self.spi.write(bytes([0x1E, offset, 0x00]))
        res = self.spi.read(length)
        self.nss.value(1)
        return res

    def get_status(self):
        res = self.read_cmd(0xC0, dummy_bytes=0, r_len=1)
        status = res[0]
        chip_mode = (status >> 4) & 0x07
        cmd_status = (status >> 1) & 0x07
        modes = ["Unused", "RFU", "STDBY_RC", "STDBY_XOSC", "FS", "RX", "TX"]
        c_mode_str = modes[chip_mode] if chip_mode < len(modes) else "Unknown"
        print(f"[SX1262 Status] Raw: {hex(status)} | Mode: {c_mode_str} | Cmd Status: {cmd_status}")
        return status

    def init_radio(self):
        self.hw_reset()
        print("[SX1262] Setting Standby Mode (RC)...")
        self.write_cmd(0x80, b'\x00') 
        self.get_status()

        print("[SX1262] Configuring Regulator Mode (DCDC)...")
        self.write_cmd(0x96, b'\x01') 

        print("[SX1262] Configuring TCXO control via DIO3 (1.8V)...")
        self.write_cmd(0x97, b'\x02\x00\x00\x64') 

        print("[SX1262] Configuring RF Switch path via DIO2...")
        self.write_cmd(0x9D, b'\x01') 

        print("[SX1262] Calibrating Image (863-870 MHz band)...")
        self.write_cmd(0x98, b'\xD7\xDB') 

        print("[SX1262] Executing internal Calibration...")
        self.write_cmd(0x89, b'\x7F') 
        time.sleep_ms(10)

        print("[SX1262] Adjusting Over-Current Protection (OCP) to 140mA...")
        self.write_reg(0x08E7, b'\x38') 

        print("[SX1262] Setting Packet Type to LoRa...")
        self.write_cmd(0x8A, b'\x01') 

    def config_rf_params(self, freq_hz, sf, bw_idx, is_rx=False):
        print(f"[SX1262 RF] Tuning to {freq_hz} Hz | SF{sf} | BW Index {bw_idx}")
        freq_factor = int((freq_hz * 33554432) / 32000000)
        self.write_cmd(0x86, struct.pack(">I", freq_factor))

        ldro = 0x01 if (sf >= 11 and bw_idx == 4) else 0x00
        mod_params = bytes([sf, bw_idx, TX_CR, ldro])
        self.write_cmd(0x8B, mod_params)

        # LoRaWAN downlinks (RX) DO NOT pass explicit physical CRC footers.
        crc_setup = 0x00 if is_rx else 0x01
        iq_setup  = 0x01 if is_rx else 0x00
        
        pkt_params = bytes([0x00, TX_PREAMBLE, 0x00, 0xFF, crc_setup, iq_setup])
        self.write_cmd(0x8C, pkt_params)
        self.write_reg(0x0740, b'\x34\x44') # LoRaWAN Public Sync Word

    def tx_packet(self, payload):
        print(f"[SX1262 TX] Payload Data: {ubinascii.hexlify(payload).decode().upper()}")
        
        self.write_cmd(0x8F, b'\x00\x00') 
        self.write_buffer(0x00, payload)

        pkt_params = bytes([0x00, TX_PREAMBLE, 0x00, len(payload), 0x01, 0x00])
        self.write_cmd(0x8C, pkt_params)

        print("[SX1262 TX] Reconfiguring Tx Power Blocks...")
        self.write_cmd(0x8E, b'\x0E\x04')

        print("[SX1262 TX] Clearing pre-existing Interrupt vectors...")
        self.write_cmd(0x02, b'\xFF\xFF') # FIXED: Opcode 0x02 clears interrupts

        print("[SX1262 TX] Setting IRQ Mask for TX Complete...")
        self.write_cmd(0x08, b'\x00\x01\x00\x01\x00\x00\x00\x00') # Opcode 0x08 maps them to pins

        print("[SX1262 TX] Putting Radio into active TX State...")
        self.write_cmd(0x83, b'\x00\x00\x00')

        start = time.ticks_ms()
        while self.dio1.value() == 0:
            if time.ticks_diff(time.ticks_ms(), start) > 5000:
                print("[SX1262 TX] Error: TX State timed out internally!")
                return False
            time.sleep_ms(5)

        irq_flags = self.read_cmd(0x12, dummy_bytes=1, r_len=2)
        flags = struct.unpack(">H", irq_flags)[0]
        
        if flags & 0x0001: # TxDone
            print("[SX1262 TX] Hardware Verified: TX Done!")
            self.write_cmd(0x02, b'\xFF\xFF') # FIXED: Opcode 0x02 clears interrupts
            return True
        return False

    def start_rx(self, timeout_ms):
        # FIXED: Opcode 0x02 completely clears previous statuses so RX starts fresh
        self.write_cmd(0x02, b'\xFF\xFF')
        
        # Opcode 0x08 configures tracking parameters for RxDone, Timeout, HeaderErr, CrcErr
        self.write_cmd(0x08, b'\x02\x62\x02\x62\x00\x00\x00\x00')

        ticks = int((timeout_ms * 1000) / 15.625)
        tick_bytes = struct.pack(">I", ticks)[1:4]

        print(f"[SX1262 RX] Initiating Receiver window for {timeout_ms}ms...")
        self.write_cmd(0x82, tick_bytes)

    def monitor_rx(self, timeout_ms):
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            if self.dio1.value() == 1:
                irq = struct.unpack(">H", self.read_cmd(0x12, dummy_bytes=1, r_len=2))[0]
                print(f"[SX1262 RX] Interrupt Event Tracked: {hex(irq)}")
                
                if irq & 0x0002: # RxDone
                    if irq & 0x0040:
                        print("[SX1262 RX] Alert: Packet Corrupted! (CRC Error)")
                        self.write_cmd(0x02, b'\xFF\xFF') # FIXED
                        return None
                    if irq & 0x0020:
                        print("[SX1262 RX] Alert: Header Check Failed!")
                        self.write_cmd(0x02, b'\xFF\xFF') # FIXED
                        return None
                    
                    rx_status = self.read_cmd(0x13, dummy_bytes=1, r_len=3)
                    payload_len = rx_status[0]
                    rx_start_buffer = rx_status[1]
                    
                    packet_status = self.read_cmd(0x14, dummy_bytes=1, r_len=3)
                    rssi = -packet_status[0] / 2
                    snr = int.from_bytes(bytes([packet_status[1]]), 'big')
                    if snr > 127: snr -= 256
                    snr = snr / 4
                    
                    print(f"[SX1262 RX] Frame captured! Size: {payload_len} bytes | RSSI: {rssi} dBm | SNR: {snr} dB")
                    data = self.read_buffer(rx_start_buffer, payload_len)
                    self.write_cmd(0x02, b'\xFF\xFF') # FIXED
                    return data
                    
                if irq & 0x0200: # Timeout
                    print("[SX1262 RX] Native hardware timeout triggered.")
                    self.write_cmd(0x02, b'\xFF\xFF') # FIXED
                    return None
                    
                self.write_cmd(0x02, b'\xFF\xFF') # FIXED
                
            time.sleep_ms(5)
        print("[SX1262 RX] Host execution window expired without capture.")
        return None
# ============================================================================
# MAIN ORCHESTRATION LAYER
# ============================================================================
def main():
    print("=====================================================")
    print("   LoRaWAN 1.0.4 Pure MicroPython OTAA Bootstrapper   ")
    print("=====================================================\n")

    dev_eui  = ubinascii.unhexlify(DEV_EUI_HEX)
    join_eui = ubinascii.unhexlify(JOIN_EUI_HEX)
    app_key  = ubinascii.unhexlify(APP_KEY_HEX)

    radio = SX1262()
    radio.init_radio()

    mhdr = b'\x00' # MType = Join Request
    
    import random
    random.seed(time.ticks_us())
    dev_nonce = struct.pack("<H", random.getrandbits(16))
    
    join_req_msg = mhdr + reverse_bytes(join_eui) + reverse_bytes(dev_eui) + dev_nonce
    
    mic = aes_cmac(app_key, join_req_msg)[:4]
    full_packet = join_req_msg + mic

    print("\n--- [LoRaWAN TX Construction] ---")
    print(f"JoinEUI (AppEUI) : {JOIN_EUI_HEX}")
    print(f"DevEUI           : {DEV_EUI_HEX}")
    print(f"DevNonce         : {ubinascii.hexlify(dev_nonce).decode().upper()}")
    print(f"Calculated MIC   : {ubinascii.hexlify(mic).decode().upper()}")
    print(f"Assembled Frame  : {ubinascii.hexlify(full_packet).decode().upper()}\n")

    tx_freq = UPLINK_CHANNELS[0]
    radio.config_rf_params(tx_freq, TX_SF, TX_BW, is_rx=False)
    
    tx_timestamp = time.ticks_ms()
    if not radio.tx_packet(full_packet):
        print("Fatal error: Transmission failed.")
        return

    # Offset sleep calculations slightly early (-50ms) to counteract execution delays
    rx1_target_ms = tx_timestamp + JOIN_TIMEOUT_RX1_MS - 50 
    now = time.ticks_ms()
    delay_before_rx1 = time.ticks_diff(rx1_target_ms, now)
    
    if delay_before_rx1 > 0:
        print(f"[Timing] Holding processing state for {delay_before_rx1}ms before checking RX1...")
        time.sleep_ms(delay_before_rx1)

    print("\n--- [Opening Receive Window 1 (RX1)] ---")
    radio.config_rf_params(tx_freq, TX_SF, TX_BW, is_rx=True)
    radio.start_rx(timeout_ms=1000)
    rx_data = radio.monitor_rx(timeout_ms=10000)

    if rx_data is None:
        print("\n[RX1] Window empty. Shifting parameters to alternate track...")
        rx2_target_ms = tx_timestamp + JOIN_TIMEOUT_RX2_MS - 50
        now = time.ticks_ms()
        delay_before_rx2 = time.ticks_diff(rx2_target_ms, now)
        if delay_before_rx2 > 0:
            print(f"[Timing] Holding processing state for {delay_before_rx2}ms before checking RX2...")
            time.sleep_ms(delay_before_rx2)

        print("\n--- [Opening Receive Window 2 (RX2)] ---")
        radio.config_rf_params(RX2_FREQ, RX2_SF, RX2_BW, is_rx=True)
        radio.start_rx(timeout_ms=1000)
        rx_data = radio.monitor_rx(timeout_ms=10000)

    if rx_data is None:
        print("\n=====================================================")
        print("  RESULT: JOIN FAILED (No response tracked within window constraints)")
        print("=====================================================")
        return

    print(f"\n[Downlink Received] Raw bytes: {ubinascii.hexlify(rx_data).decode().upper()}")
    
    if len(rx_data) < 17:
        print("Error: Received frame size breaks protocol minimums for Join Accept.")
        return

    mhdr_rx = rx_data[0]
    if (mhdr_rx >> 5) != 1:
        print("Warning: Downlink packet header does not validate as a Join Accept frame type.")

    encrypted_payload = rx_data[1:]
    decrypted_payload = bytearray()
    
    cipher = ucryptolib.aes(app_key, 1)
    for i in range(0, len(encrypted_payload), 16):
        block = encrypted_payload[i:i+16]
        if len(block) == 16:
            decrypted_payload.extend(cipher.encrypt(block))

    print(f"[Crypto] Decrypted Assembly Payload: {ubinascii.hexlify(decrypted_payload).decode().upper()}")

    join_nonce = decrypted_payload[0:3]
    net_id     = decrypted_payload[3:6]
    dev_addr   = decrypted_payload[6:10]
    dl_settings = decrypted_payload[10]
    rx_delay   = decrypted_payload[11]
    
    received_mic = decrypted_payload[-4:]
    mac_content  = bytes([mhdr_rx]) + decrypted_payload[:-4]
    
    computed_mic = aes_cmac(app_key, mac_content)[:4]
    
    print("\n--- [Integrity Signature Verification] ---")
    print(f"Received MIC : {ubinascii.hexlify(received_mic).decode().upper()}")
    print(f"Computed MIC : {ubinascii.hexlify(computed_mic).decode().upper()}")
    
    if received_mic != computed_mic:
        print("\n=====================================================")
        print("  CRITICAL ERROR: MIC Verification failed! Packet rejected.")
        print("=====================================================")
        return
    print("Integrity Pass: Local checksum maps perfectly to payload validation context!")

    padding_block = b'\x00' * 7
    nwk_key_input = b'\x01' + join_nonce + net_id + dev_nonce + padding_block
    app_key_input = b'\x02' + join_nonce + net_id + dev_nonce + padding_block
    
    nwk_s_key = aes_128_ecb_encrypt(app_key, nwk_key_input)
    app_s_key = aes_128_ecb_encrypt(app_key, app_key_input)

    print("\n=====================================================")
    print("  OTAA JOIN INITIALIZATION SUCCESSFUL!")
    print("=====================================================")
    print(f"JoinNonce   : {ubinascii.hexlify(join_nonce).decode().upper()}")
    print(f"NetID       : {ubinascii.hexlify(net_id).decode().upper()}")
    print(f"DevAddr     : {ubinascii.hexlify(reverse_bytes(dev_addr)).decode().upper()} (Big Endian Display)")
    print(f"DLSettings  : {hex(dl_settings)}")
    print(f"RXDelay     : {rx_delay} second(s)")
    print(f"NwkSKey     : {ubinascii.hexlify(nwk_s_key).decode().upper()}")
    print(f"AppSKey     : {ubinascii.hexlify(app_s_key).decode().upper()}")
    print("=====================================================\n")

if __name__ == '__main__':
    main()