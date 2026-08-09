"""防休眠 — 分析期间保持电脑唤醒 (Windows)

用法:
  python tools/keep_awake.py          # 前台运行，Ctrl+C 停止并恢复休眠
  python tools/keep_awake.py --bg     # 后台静默运行
  python tools/keep_awake.py --stop   # 停止后台进程
"""
import ctypes, sys, time, subprocess
from pathlib import Path

PID_FILE = Path(__file__).resolve().parent.parent / '.keep_awake_pid'

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

def keep_awake():
    ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)

def allow_sleep():
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

def main():
    if '--stop' in sys.argv:
        if PID_FILE.exists():
            pid = PID_FILE.read_text().strip()
            subprocess.run(['taskkill', '/F', '/PID', pid],
                          capture_output=True)
            PID_FILE.unlink()
            print(f'已停止 (PID: {pid})')
        else:
            print('没有运行中的后台进程')
        return

    if '--bg' in sys.argv:
        # 后台模式：启动独立pythonw进程
        script = str(Path(__file__).resolve())
        proc = subprocess.Popen(
            ['pythonw', script, '--_daemon'],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
        PID_FILE.write_text(str(proc.pid))
        print(f'后台运行 (PID: {proc.pid})')
        return

    if '--_daemon' in sys.argv:
        # 守护进程：持续防休眠
        allow_sleep()
        keep_awake()
        while True:
            time.sleep(60)

    # 前台模式
    print('已开启防休眠 | Ctrl+C 停止')
    allow_sleep()
    keep_awake()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        allow_sleep()
        print('已恢复休眠')

if __name__ == '__main__':
    main()
