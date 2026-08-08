import subprocess, sys
os.chdir(r"d:\足球大模型1.0")
r = subprocess.run(["git", "commit", "-m", "pipeline: DeepSeek LLM + lottery Aug9 24 predictions"],
                   capture_output=True, text=True)
print("STDOUT:", r.stdout)
print("STDERR:", r.stderr)
print("RC:", r.returncode)
r2 = subprocess.run(["git", "push", "origin", "master"], capture_output=True, text=True, timeout=60)
print("PUSH STDOUT:", r2.stdout)
print("PUSH STDERR:", r2.stderr)
