import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import self_upgrade as su
print("self_upgrade.__file__ =", su.__file__)

diag = su.diagnose()
print("diag keys:", list(diag.keys()))
if "module" in diag:
    print("diag.module =", diag["module"])
    print("diag.source length =", len(diag.get("source", "")))
    fix = su.generate_fix(diag)
    print("fix is None?", fix is None)
    if fix:
        print("fix length:", len(fix))
        print("fix starts with:", repr(fix[:160]))
        print("fix contains 'data: {':", 'data: {' in fix)
        val = su.validate(fix, diag["module"], original_source=diag["source"])
        print("validate:", val)
