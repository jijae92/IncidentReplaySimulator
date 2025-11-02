import os, re, json, sys, pathlib

code_dir = pathlib.Path(os.environ.get("IRS_CODE_DIR", "src/replay_orchestrator"))
if not code_dir.exists():
    print(f"ERROR: code dir not found: {code_dir}", file=sys.stderr)
    sys.exit(1)

env_keys, evt_keys = set(), set()
env_pat = re.compile(r"os\.(?:environ[\'\"]([A-Z0-9_:\-]+)[\'\"]|getenv[\'\"]([A-Z0-9_:\-]+)[\'\"])")
evt_pat = re.compile(r"event[\'\"]([A-Za-z0-9_:\-]+)[\'\"]|event\.get[\'\"]([A-Za-z0-9_:\-]+)[\'\"])")

# 하위 모든 .py 재귀 스캔
for f in code_dir.rglob("*.py"):
    try:
        s = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for a,b in env_pat.findall(s):
        if a: env_keys.add(a)
        if b: env_keys.add(b)
    for a,b in evt_pat.findall(s):
        if a: evt_keys.add(a)
        if b: evt_keys.add(b)

env_path = os.environ.get("IRS_ENV_PATH", "env/replay_orchestrator.json")
evt_path = os.environ.get("IRS_EVT_PATH", "events/replay.json")

def load_json(p):
    try:
        import json, io
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

env_json = load_json(env_path)
evt_json = load_json(evt_path)

env_vars = {}
try:
    env_vars = env_json["ReplayOrchestratorFunction"]
except Exception:
    env_vars = {}

missing_env = sorted([k for k in env_keys if not env_vars or (env_vars.get(k) in (None, "", "null"))])
missing_evt = sorted([k for k in evt_keys if (evt_json.get(k) in (None, "", "null") or k not in evt_json)])

print("=== Required keys discovered from code ===")
print(f"- ENV required ({len(env_keys)}): {', '.join(sorted(env_keys)) or '(none)'}")
print(f"- EVT required ({len(evt_keys)}): {', '.join(sorted(evt_keys)) or '(none)'}\n")

print("=== Present vs Missing ===")
print(f"- Missing ENV ({len(missing_env)}): {', '.join(missing_env) or '(none)'}")
print(f"- Missing EVT ({len(missing_evt)}): {', '.join(missing_evt) or '(none)'}")
