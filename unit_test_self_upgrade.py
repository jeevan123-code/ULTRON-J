import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from self_upgrade import generate_fix, validate, _parse_stream_llm_output, _top_level_defs

# A — SSE chunks like stream_llm actually emits
def fake_stream():
    yield 'data: {"token": "import os"}\n\n'
    yield 'data: {"token": "\\n"}\n\n'
    yield 'data: {"token": "def hi(): return 1\\n"}\n\n'
    yield 'data: {"_full": "import os\\ndef hi(): return 1\\n"}\n\n'
parsed = _parse_stream_llm_output(fake_stream())
print("A parsed:", repr(parsed))

# B — validate must reject corrupted SSE blob
original_src = "def foo(): pass\ndef bar(): pass\n"
corrupt_sse = 'data: {"token": "abc"}\n\ndata: {"token": "def"}\n'
val_bad = validate(corrupt_sse, "fake_mod", original_source=original_src)
print("B validate(corrupt):", val_bad)

# C — validate must accept a good replacement
good = "def foo():\n    return 1\ndef bar():\n    return 2\n"
val_good = validate(good, "fake_mod", original_source=original_src)
print("C validate(good):", val_good)

# D — top-level defs
print("D top_level_defs(original):", _top_level_defs(original_src))
print("D top_level_defs(good):", _top_level_defs(good))
print("D top_level_defs(corrupt):", _top_level_defs(corrupt_sse))
