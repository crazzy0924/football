"""
🚨 推送前汉化检查 · v1.0
规则: 所有用户可见内容必须中文 · 不通过不准 push
用法: python pre_push_check.py
退出码: 0=通过 1=违规
"""
import sys, io, re, subprocess, json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = Path(__file__).resolve().parent

# 连续2+英文单词片段 → 队名漏译检测 ("IF Elfsborg"/"Al Ettifaq"/"Viking FK")
# 至少一个词≥4字母, 避免误报中文队名前缀("TPS图尔库"的"vs TPS")
WORDSEQ = re.compile(r'(?=[A-Za-z\s]*[A-Za-z]{4,})[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})+')

VIOLATIONS = 0

def viol(filename: str, line: int, detail: str):
    global VIOLATIONS
    VIOLATIONS += 1
    print(f"  ❌ {filename}:{line} → {detail}")

def is_html_tag_or_css(line: str) -> bool:
    """纯HTML/CSS结构行不算违规"""
    s = line.strip()
    if not s:
        return True
    # CSS规则
    if s.startswith('{') or s.startswith('}') or s.endswith('{') or s.endswith('}'):
        return True
    if s.startswith('--') or s.startswith('/*') or s.startswith('*'):
        return True
    # HTML标签属性
    if s.startswith('<') and ('=' in s or s.startswith('</') or s.startswith('<!--')):
        return True
    # 纯数字/符号
    if not re.search(r'[a-zA-Z]{3,}', s):
        return True
    # CSS选择器/属性 (含冒号但不在中文语境)
    if ':' in s and '{' not in s and not any('一' <= c <= '鿿' for c in s):
        return True
    # import/from/def/class/var/const/let 是代码
    code_kw = ['import ', 'from ', 'def ', 'class ', 'return ', 'const ', 'let ', 'var ',
               'async ', 'await ', 'export ', 'function ', 'require(', 'console.',
               'print(', 'pathlib', 'json.', 'open(', '.json', '.html']
    for kw in code_kw:
        if s.startswith(kw) or kw in s:
            return True
    return False

def has_english_content(text: str) -> list[tuple[int, str]]:
    """返回(行号, 违规行)列表 · 排除纯代码标记行"""
    violations = []
    lines = text.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if is_html_tag_or_css(line):
            continue
        # 计算英文字母占比
        alpha_chars = sum(1 for c in stripped if c.isalpha() and c.isascii())
        cjk_chars = sum(1 for c in stripped if '一' <= c <= '鿿')
        total_alpha = sum(1 for c in stripped if c.isalpha())
        if total_alpha < 6:
            continue  # 太短，不检查
        # 英文占主导(>60%) 且 无明显中文 → 违规
        if total_alpha > 0:
            ascii_ratio = alpha_chars / total_alpha
            if ascii_ratio > 0.6 and cjk_chars < 3 and total_alpha > 10:
                # 再排除一些: CSS class名、HTML属性等
                if not re.match(r'^[\s\w\-\.,:;{}()\[\]"\'=><*+/@!#$%^&|`~]+$', stripped):
                    continue  # 含特殊字符的可能是混合内容
                violations.append((i + 1, stripped[:120]))
    return violations

def check_commit_message() -> bool:
    """检查最近的commit message是否中文"""
    try:
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%s'],
            capture_output=True, text=True, encoding='utf-8', cwd=ROOT
        )
        msg = result.stdout.strip()
        cjk = sum(1 for c in msg if '一' <= c <= '鿿')
        if cjk < 3:
            viol('(commit message)', 0, f'commit message缺少中文: "{msg[:80]}"')
            return False
        return True
    except Exception as e:
        print(f'  ⚠ 无法检查commit message: {e}')
        return True  # 不阻塞

def check_staged_file(filepath: Path):
    """检查单个文件的可见文本"""
    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        print(f'  ⚠ 无法读取 {filepath}: {e}')
        return

    ext = filepath.suffix.lower()
    rel = str(filepath.relative_to(ROOT))

    if ext == '.py':
        # Python: 检查print字符串、注释中的英文
        lines = content.split('\n')
        for i, line in enumerate(lines):
            s = line.strip()
            # 检查注释内容
            if s.startswith('#') and not s.startswith('#!'):
                comment = s[1:].strip()
                alpha = sum(1 for c in comment if c.isalpha() and c.isascii())
                cjk = sum(1 for c in comment if '一' <= c <= '鿿')
                if alpha > 15 and cjk == 0:
                    viol(rel, i + 1, f'英文注释: {comment[:100]}')
            # 检查print/echo字符串
            for m in re.finditer(r'print\(f?["\']([^"\']{20,})["\']', line):
                txt = m.group(1)
                alpha = sum(1 for c in txt if c.isalpha() and c.isascii())
                cjk = sum(1 for c in txt if '一' <= c <= '鿿')
                if alpha > 15 and cjk == 0 and not txt.startswith('http'):
                    viol(rel, i + 1, f'英文输出: {txt[:100]}')

    elif ext == '.html':
        # HTML: 检查可见文本内容
        # 先提取纯文本(去掉标签和CSS)
        text = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', '\n', text)
        text = re.sub(r'\{[^}]*\}', '', text)  # 内联CSS
        text = re.sub(r'^\s*[\w\-\.#:;,\s{}()\[\]"\'=><*+/@!#$%^&|`~]+\s*$', '', text, flags=re.MULTILINE)

        for i, line in enumerate(text.split('\n')):
            s = line.strip()
            if len(s) < 15:
                continue
            # 新规则(8-14确立): 连续2+英文单词片段("IF Elfsborg"/"Al Ettifaq") → 违规
            # 旧规则漏点: 中文行混英文队名时 cjk≥3 整行放行
            for m in WORDSEQ.finditer(s):
                viol(rel, i + 1, f'英文可见片段: ...{s[max(0,m.start()-10):m.end()+10]}...')
            alpha = sum(1 for c in s if c.isalpha() and c.isascii())
            cjk = sum(1 for c in s if '一' <= c <= '鿿')
            # 如果有≥3个中文字符 → 中文句子含英文专有名词(Dixon-Coles等)，通过
            if cjk >= 3:
                continue
            if alpha > 10 and cjk == 0:
                viol(rel, i + 1, f'英文可见文本: {s[:120]}')

    elif ext == '.json':
        # JSON: 检查字符串值 (投注单等用户可见JSON, 队名必须中文)
        def check_json_value(v, path=''):
            if isinstance(v, str):
                for m in WORDSEQ.finditer(v):
                    viol(rel, 0, f'JSON英文片段{path}: {v[max(0,m.start()-10):m.end()+10]}')
            elif isinstance(v, dict):
                for k, val in v.items():
                    check_json_value(val, f'{path}.{k}')
            elif isinstance(v, list):
                for idx, item in enumerate(v):
                    check_json_value(item, f'{path}[{idx}]')

        try:
            data = json.loads(content)
            check_json_value(data)
        except json.JSONDecodeError:
            pass  # 非标准JSON，跳过

    elif ext == '.md':
        # Markdown: 检查可见文本，跳过代码块
        in_code_block = False
        for i, line in enumerate(content.split('\n')):
            s = line.strip()
            if s.startswith('```'):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue  # 代码块内的命令/代码允许英文
            if s.startswith('---') or s.startswith('#'):
                continue
            if s.startswith('![') or s.startswith('['):
                continue
            # 允许链接行 (含URL)、行内代码
            if 'http' in s or s.startswith('- [') or '`' in s:
                continue
            alpha = sum(1 for c in s if c.isalpha() and c.isascii())
            cjk = sum(1 for c in s if '一' <= c <= '鿿')
            if alpha > 20 and cjk < 3 and '|' not in s:
                viol(rel, i + 1, f'英文Markdown文本: {s[:120]}')


# ===== MAIN =====
print('🔍 推送前汉化检查...')
print()

# 1. 检查已暂存(staged)的文件
result = subprocess.run(
    ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR'],
    capture_output=True, text=True, encoding='utf-8', cwd=ROOT
)
staged = [ROOT / f for f in result.stdout.strip().split('\n') if f]

# 如果没有staged文件，检查working tree变更
if not staged:
    result = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=ACMR'],
        capture_output=True, text=True, encoding='utf-8', cwd=ROOT
    )
    staged = [ROOT / f for f in result.stdout.strip().split('\n') if f]
    print(f'📋 无暂存文件，检查工作区变更 ({len(staged)}个文件)')
else:
    print(f'📋 检查暂存文件 ({len(staged)}个文件)')

# 过滤: 只检查内容文件（跳过缓存/二进制/state/模型权重）
content_files = [f for f in staged if f.exists() and f.suffix.lower() in
    ('.html', '.py', '.json', '.md', '.txt')]
content_files = [f for f in content_files if '__pycache__' not in str(f)]
content_files = [f for f in content_files if 'data/state/' not in str(f).replace(chr(92), '/')]
# 自检豁免
content_files = [f for f in content_files if f.name not in ('pre_push_check.py',)]
# JSON数据文件豁免 — 机器内部数据(队名/联赛代码必须英文才能匹配ELO)
# 注意: pinnacle_bets_ 是投注单(用户可见) → 不豁免, 队名必须中文 (8-14修正)
content_files = [f for f in content_files if not (f.suffix == '.json' and (
    'today.json' in f.name or 'pinnacle_odds_' in f.name
    or 'predictions_' in f.name or 'kambi_' in f.name or 'local_match_db' in f.name))]

print(f'🔎 检查 {len(content_files)} 个内容文件...')
print()

for f in content_files:
    check_staged_file(f)

# 3. 检查commit message
print()
print('📝 检查commit message...')
check_commit_message()

print()
if VIOLATIONS > 0:
    print(f'{"="*60}')
    print(f'🚨 发现 {VIOLATIONS} 处违规！推送前必须全部修改为中文。')
    print(f'{"="*60}')
    sys.exit(1)
else:
    print('✅ 汉化检查通过 · 可以推送')
    sys.exit(0)
