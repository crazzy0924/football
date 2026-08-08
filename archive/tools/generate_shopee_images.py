"""
Shopee 菲律宾站 - 软管喷嘴带泡罩包装 商品套图生成
====================================================
1张主图 + 8张副图，使用 HuggingFace FLUX.1-schnell Space (免费)
无需 API Key，无需注册

使用方式:
  python tools/generate_shopee_images.py
  图片输出到: output/shopee_images/
"""

import sys
import time
import json
import shutil
from pathlib import Path
from datetime import datetime

from gradio_client import Client

# 修复 Windows 终端编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ============================================================
# 配置
# ============================================================
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "shopee_images"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WIDTH, HEIGHT = 1024, 1024
NUM_STEPS = 4  # FLUX.1-schnell 推荐 1-4 步
DELAY_BETWEEN = 2  # 请求间隔 (秒)
QUOTA_RETRY_DELAY = 15  # ZeroGPU 配额用完后等待秒数
MAX_RETRIES = 10  # 单张图片最大重试次数

# ============================================================
# 9 张图片 Prompt 定义
# ============================================================

def get_all_prompts() -> list[dict]:
    """主图 + 8副图"""

    return [
        # ===== 01: 主图 - 白底正面 =====
        {
            "filename": "01_MAIN_front_view.jpg",
            "title": "[1/9] 主图-正面白底",
            "prompt": (
                "Professional e-commerce product photography on pure white background, front view. "
                "A green ABS plastic garden hose spray nozzle gun with a black round spray head, "
                "ergonomic pistol-grip handle with black rubberized panels, metal trigger, "
                "brass connector at bottom. "
                "The black rotating nozzle ring has molded embossed English words FULL and CONE as physical plastic markings. "
                "Packaged in transparent plastic blister on printed cardboard backing card. "
                "Studio lighting, sharp focus edge to edge, product fills 80 percent of frame, "
                "clean white background with no shadows, commercial product catalog style, color accurate"
            ),
        },

        # ===== 02: 背面 =====
        {
            "filename": "02_back_view.jpg",
            "title": "[2/9] 背面-纸卡信息",
            "prompt": (
                "Professional product photo on pure white background, back side view. "
                "The reverse side of a green garden hose spray nozzle in blister card packaging. "
                "The cardboard backing card shows printed product specifications, barcode, and diagrams. "
                "The green spray nozzle is visible inside the transparent plastic blister from behind. "
                "The nozzle ring has molded embossed English text FULL and CONE. "
                "Studio lighting, product fills 80 percent of frame, sharp focus, clean white background"
            ),
        },

        # ===== 03: 45度侧视角 =====
        {
            "filename": "03_angle_view.jpg",
            "title": "[3/9] 45度侧视角",
            "prompt": (
                "Professional product photo on pure white background, shot at 45 degree angle. "
                "A green and black garden hose spray nozzle in blister card packaging, "
                "showing both the front face and side profile. "
                "The ergonomic pistol grip shape and blister packaging depth are visible. "
                "The transparent plastic blister has subtle light reflections. "
                "The nozzle ring has molded embossed text FULL and CONE as physical plastic markings. "
                "Studio lighting, product fills 80 percent of frame, sharp focus, clean white background"
            ),
        },

        # ===== 04: 喷头微距特写 =====
        {
            "filename": "04_nozzle_closeup.jpg",
            "title": "[4/9] 喷头微距特写",
            "prompt": (
                "Macro close-up product photo of a garden hose spray nozzle head. "
                "Extreme close-up on the black rotating selector ring. "
                "The ring has molded embossed English words FULL and CONE clearly visible "
                "as physical engraved plastic texture markings, not printed text. "
                "The center black spray tip shows multiple small water outlet holes in a circular pattern. "
                "Green matte ABS plastic body texture is visible. "
                "Macro lens photography, shallow depth of field, sharp focus on the text ring, "
                "pure white background, studio lighting"
            ),
        },

        # ===== 05: 喷水模式演示 =====
        {
            "filename": "05_spray_patterns.jpg",
            "title": "[5/9] 喷水模式演示",
            "prompt": (
                "Lifestyle product photo in a bright sunny garden. "
                "A persons hand holding a green and black garden hose spray nozzle without any packaging, "
                "actively spraying water. "
                "The water creates a beautiful wide cone shaped mist spray with tiny rainbow sparkles. "
                "The nozzle ring has molded text FULL and CONE as physical markings. "
                "Background shows blurred green plants and colorful blooming flowers. "
                "Natural sunlight, professional lifestyle photography, bright fresh garden atmosphere"
            ),
        },

        # ===== 06: 尺寸参考 =====
        {
            "filename": "06_dimensions.jpg",
            "title": "[6/9] 尺寸参考图",
            "prompt": (
                "Product photo on pure white background. A green and black garden hose spray nozzle gun "
                "laid horizontally on a surface. Next to it is a yellow measuring tape ruler "
                "showing centimeter scale markings. The nozzle is approximately 15 to 20 cm long. "
                "The rotating ring shows molded text FULL and CONE as plastic markings. "
                "Top down view, studio lighting, sharp detail on ruler, clean white background"
            ),
        },

        # ===== 07: 包装纸卡细节 =====
        {
            "filename": "07_packaging_detail.jpg",
            "title": "[7/9] 包装纸卡细节",
            "prompt": (
                "Flat lay product photo on pure white background. "
                "The printed cardboard backing card of a blister pack laid flat, "
                "showing colorful printed product graphics with feature icons and brand logo design. "
                "The green hose spray nozzle placed beside the card for scale. "
                "The nozzle ring has molded text FULL and CONE as physical plastic markings. "
                "Overhead flat lay style, studio lighting, sharp on printed card details, clean white background"
            ),
        },

        # ===== 08: 接口握把特写 =====
        {
            "filename": "08_connector_detail.jpg",
            "title": "[8/9] 接口握把特写",
            "prompt": (
                "Macro product photo on pure white background, bottom angle view. "
                "Close-up of the bottom connector and handle area of a green garden hose spray nozzle gun. "
                "Focus on the brass quick connector fitting for standard garden hose, "
                "the black rubberized textured grip panels, and the metal trigger. "
                "The rotating head ring with molded FULL and CONE text is partially visible. "
                "Macro lens, sharp focus on connector mechanism, studio lighting, clean white background"
            ),
        },

        # ===== 09: 花园实拍场景 =====
        {
            "filename": "09_in_use_garden.jpg",
            "title": "[9/9] 花园实拍场景",
            "prompt": (
                "Beautiful lifestyle product photo in a lush home garden. "
                "A persons hand gently holding a green and black garden hose spray nozzle without packaging, "
                "spraying a soft cone shaped water mist onto vibrant blooming roses and daisies. "
                "Sunny day with warm natural lighting filtering through leaves. "
                "Green grass in background. Water creates tiny rainbow sparkles. "
                "The nozzle ring has molded text FULL and CONE as physical plastic markings. "
                "Professional lifestyle photography, shallow depth of field with bokeh, "
                "aspirational home gardening atmosphere, bright and fresh colors"
            ),
        },
    ]


# ============================================================
# 图片转换 (webp -> jpg)
# ============================================================

def convert_to_jpg(src_path: str, dst_path: str) -> int:
    """将 webp/png 转为 jpg，返回文件大小"""
    try:
        from PIL import Image
        img = Image.open(src_path)
        # 转 RGB (webp 可能是 RGBA)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(dst_path, "JPEG", quality=95)
        return Path(dst_path).stat().st_size
    except ImportError:
        # 没有 PIL，直接复制
        shutil.copy(src_path, dst_path)
        return Path(dst_path).stat().st_size


# ============================================================
# 主流程
# ============================================================

def main():
    print("""
╔══════════════════════════════════════════════════════╗
║     Shopee 菲律宾站 - 商品套图生成器                   ║
║     产品: 软管喷嘴带泡罩包装                           ║
║     方案: 1 主图 + 8 副图                              ║
║     模型: FLUX.1-schnell (HuggingFace Space, 免费)    ║
║     输出: output/shopee_images/
╚══════════════════════════════════════════════════════╝
""")

    # 连接 FLUX Space
    print("正在连接 FLUX.1-schnell Space...", end=" ", flush=True)
    try:
        client = Client("black-forest-labs/FLUX.1-schnell")
        print("已连接!")
    except Exception as e:
        print(f"\n连接失败: {e}")
        print("请检查网络是否能访问 huggingface.co")
        return

    prompts = get_all_prompts()
    total = len(prompts)
    print(f"共 {total} 张待生成\n")
    print("-" * 60)

    results = []
    start_time = time.time()

    for i, task in enumerate(prompts, 1):
        filename = task["filename"]
        title = task["title"]
        prompt = task["prompt"]
        jpg_path = OUTPUT_DIR / filename

        print(f"\n{title}")

        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            t_start = time.time()
            status = f"[Attempt {attempt}]" if attempt > 1 else ""
            print(f"  生成中...{status}", end=" ", flush=True)

            try:
                # 调用 FLUX Space
                result, seed = client.predict(
                    prompt,
                    0,          # seed (0 = 随机)
                    True,       # randomize_seed
                    WIDTH,
                    HEIGHT,
                    NUM_STEPS,
                    api_name="/infer",
                )

                elapsed = time.time() - t_start
                src = result if isinstance(result, str) else result.get("path", "")
                if not src:
                    raise RuntimeError(f"No file path in result: {result}")

                convert_to_jpg(src, str(jpg_path))
                size_kb = jpg_path.stat().st_size / 1024

                print(f"OK ({size_kb:.0f} KB, {elapsed:.0f}s, seed={seed})")
                results.append({
                    "filename": filename,
                    "title": title,
                    "filepath": str(jpg_path),
                    "size_kb": round(size_kb, 1),
                    "seed": seed,
                    "status": "ok",
                })
                success = True
                break

            except Exception as e:
                emsg = str(e)
                # ZeroGPU 配额用尽 -> 等待后重试
                if "ZeroGPU quota" in emsg or "exceeded your" in emsg:
                    print(f"配额用尽, {QUOTA_RETRY_DELAY}s 后重试...")
                    time.sleep(QUOTA_RETRY_DELAY)
                    continue
                else:
                    print(f"FAIL - {e}")
                    results.append({
                        "filename": filename,
                        "title": title,
                        "error": emsg,
                        "status": "failed",
                    })
                    break

        if not success and attempt == MAX_RETRIES:
            print(f"FAIL - 已达最大重试次数 ({MAX_RETRIES})")
            results.append({
                "filename": filename,
                "title": title,
                "error": "Max retries exceeded",
                "status": "failed",
            })

        # 间隔
        if i < total:
            time.sleep(DELAY_BETWEEN)

    elapsed = time.time() - start_time

    # ========== 汇总 ==========
    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "failed"]

    print(f"\n{'='*60}")
    print(f"  完成! 耗时 {elapsed:.0f}s | 成功 {len(ok)}/{total}")
    print(f"{'='*60}")

    for r in ok:
        print(f"  [OK] {r['filename']} ({r['size_kb']} KB)")

    if failed:
        print(f"\n  失败 {len(failed)} 张:")
        for r in failed:
            print(f"  [FAIL] {r['filename']}: {r['error']}")

    # 日志
    log_path = OUTPUT_DIR / f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log_path.write_text(
        json.dumps({
            "product": "Hose Spray Nozzle with Blister Packaging",
            "generated_at": datetime.now().isoformat(),
            "provider": "huggingface FLUX.1-schnell space",
            "size": f"{WIDTH}x{HEIGHT}",
            "num_steps": NUM_STEPS,
            "elapsed_seconds": round(elapsed),
            "results": results,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n日志: {log_path}")
    print(f"图片: {OUTPUT_DIR}")
    print(f"\nShopee 上传: 主图用 01_MAIN_front_view.jpg, 副图 02-09 依次上传")

    return ok, failed


if __name__ == "__main__":
    main()
