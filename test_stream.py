 
from intelligence_core import think_and_stream

print("Starting stream test...")
for chunk in think_and_stream('who are you', 'test', [], 0.7):
    print(repr(chunk[:100]))
print("Done.")