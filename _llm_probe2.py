# -*- coding: utf-8 -*-
import os, sys, traceback
sys.stdout.reconfigure(encoding="utf-8")
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("ALL_PROXY", None)
try:
    from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL
    from deepseek_harness import DeepSeekHarness
    client = DeepSeekHarness(api_key=DEEPSEEK_API_KEY, disable_thinking_by_default=True)
    resp = client.chat(model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": "只回复两个字: 在线"}], max_tokens=20)
    print("RESP:", str(resp)[:200])
except Exception:
    traceback.print_exc()
