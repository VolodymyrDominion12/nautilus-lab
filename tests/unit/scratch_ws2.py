from websockets.sync.client import connect
import json

with connect("wss://stream.binance.com:9443/stream?streams=ethusdt@depth20@100ms") as ws:
    msg = ws.recv()
    print(json.loads(msg))
