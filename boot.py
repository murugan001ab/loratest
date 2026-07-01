import esp
esp.osdebug(None)

import gc
gc.collect()

import network

wlan=network.WLAN(network.STA_IF)

wlan.active(True)

wlan.connect('zeekers1','9629293943')