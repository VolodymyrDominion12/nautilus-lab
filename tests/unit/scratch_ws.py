from websockets.sync.client import connect
import json

with connect("wss://stream.binance.com:9443/ws/ethusdt@depth20@100ms") as ws:
    for i in range(2):
        msg = ws.recv()
        print(json.loads(msg))
