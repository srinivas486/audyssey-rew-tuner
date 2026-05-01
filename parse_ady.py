import json

with open('test.ady', 'r') as f:
    data = json.load(f)

chans = data['detectedChannels']
print(f'Channel count: {len(chans)}')
for i, ch in enumerate(chans):
    print(f'  Channel {i}: commandId={ch.get("commandId")}')
