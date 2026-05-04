#!/usr/bin/env python3
"""
text_stats.py - 网文文本统计分析工具
用于 novel-audit 技能的辅助统计，输出文本的词频、重复率、段落结构等数据。

用法：
    python text_stats.py <文本文件路径>
    python text_stats.py <文本文件路径> --mode full      # 全量分析（默认）
    python text_stats.py <文本文件路径> --mode repeat    # 只分析重复率
    python text_stats.py <文本文件路径> --mode ai        # 只检测AI特征词频
    python text_stats.py <文本文件路径> --mode structure # 只分析段落结构
"""

import sys
import re
import json
from collections import Counter
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# AI 特征词库（与 references/ai-patterns.md 保持同步）
# ──────────────────────────────────────────────────────────────────────────────

AI_PATTERN_WORDS = [
    # 情绪套话
    "心中涌现", "眼眸深处", "嘴角微微上扬", "眸子微动", "眼眸微闪",
    "深吸一口气", "心头一紧", "心中一动", "五味杂陈", "百感交集",
    "莫名的感动", "热泪盈眶", "眼眶湿润", "莫名的感慨",
    # 旁白式内心OS
    "他深知", "她深知", "他明白", "她明白", "他清楚地知道", "她清楚地知道",
    "这一刻，他终于明白", "这一刻，她终于明白", "命运的齿轮",
    "他暗自下定决心", "她暗自下定决心",
    # 行动套话
    "不动声色", "淡淡地说", "淡然道", "淡漠道", "缓缓开口", "沉默片刻",
    "沉声道", "云淡风轻", "冷冷地扫了一眼", "轻描淡写",
    # 场景套话
    "阳光透过", "空气中弥漫着", "夜风轻轻", "时间仿佛凝固", "空气都变得凝重",
    "寂静笼罩",
    # 过渡套话（高频）
    "正当此时", "就在这时", "千钧一发之际", "与此同时", "然而，谁也没想到",
    "这一切，都只是", "刚刚开始",
    # 旁观者惊叹
    "周围的人都惊呆", "倒吸一口冷气", "没有人想到", "谁也没想到",
    "人群中爆发出", "陷入一片寂静", "议论纷纷", "面面相觑",
    "所有人的目光", "在场所有人",
    # 华丽意象词堆叠（2026年5月补充）
    "璀璨", "熠熠生辉", "画卷", "华章", "乘风破浪", "扬帆起航",
    "落英缤纷", "繁星似锦", "云蒸霞蔚", "波光粼粼", "气势磅礴",
    "惊天动地", "气吞山河", "如梦似幻", "如诗如画", "美不胜收",
    "令人窒息", "肃然起敬", "悠悠岁月",
    # 抽象万能动词（2026年5月补充）
    "进行研究", "进行修炼", "开展调查", "开展工作", "实施部署",
    "发挥优势", "发挥作用", "实现突破", "实现目标", "推动发展",
    "推动变革", "达成共识", "提升效率", "打造团队", "打造品牌",
    "构建体系", "构建框架", "赋能", "激发潜力", "激发活力",
    # 翻译腔残留（2026年5月补充）
    "作为一个", "不值得", "具有重要意义",
]

# 单字/双字高频警示词（单独出现频率异常高才报警）
AI_HIGH_FREQ_SIMPLE = [
    "淡淡", "微微", "轻轻", "缓缓", "慢慢", "悄悄",
    "深邃", "冷冷", "淡然", "漠然",
    # 补充：华丽修饰词
    "璀璨", "繁华", "喧嚣", "宁静",
]

# 结构性套话（完整短语）
AI_STRUCTURE_PATTERNS = [
    r"这一切.{0,10}刚刚开始",
    r"命运的齿轮.{0,10}转动",
    r"心中.{0,5}涌现.{0,5}(股|出|起)",
    r"(他|她|主角).{0,5}深知.{0,10}",
    r"(所有人|周围的人|在场的人).{0,10}(惊呆|震惊|愕然)",
    r"(正当|就在).{0,5}(此时|这时|之际)",
    r"(他|她).{0,10}(百感交集|五味杂陈|心头一紧)",
    # 补充模式（2026年5月）
    r"不是.{2,10}，而是.{2,10}",  # 否定对举句
    r"(他|她).{0,5}(终于明白|终于懂得|终于意识到)",  # 顿悟套话
    r"这才是.{2,15}(真正|最|核心)",  # 总结式点题
    r"目光.{0,5}(深邃|悠远|复杂|冰冷|温暖)",  # 眼神万能描写
]


# ──────────────────────────────────────────────────────────────────────────────
# 核心分析函数
# ──────────────────────────────────────────────────────────────────────────────

def load_text(file_path: str) -> str:
    """读取文本文件，自动处理编码。"""
    path = Path(file_path)
    if not path.exists():
        print(f"[错误] 文件不存在: {file_path}", file=sys.stderr)
        sys.exit(1)
    for enc in ["utf-8", "gbk", "utf-16"]:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    print("[错误] 无法识别文件编码，请转为 UTF-8 后重试", file=sys.stderr)
    sys.exit(1)


def basic_stats(text: str) -> dict:
    """基础统计：字数、段落数、句子数、平均段落长度。"""
    # 去除空白行
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    # 粗略按句末标点分句
    sentences = re.split(r"[。！？…]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 2]

    para_lengths = [len(p) for p in paragraphs]
    avg_para_len = sum(para_lengths) / len(para_lengths) if para_lengths else 0

    return {
        "total_chars": len(re.sub(r"\s", "", text)),  # 不含空白的字符数
        "total_chars_with_space": len(text),
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
        "avg_para_length": round(avg_para_len, 1),
        "max_para_length": max(para_lengths) if para_lengths else 0,
        "min_para_length": min(para_lengths) if para_lengths else 0,
    }


def word_frequency(text: str, top_n: int = 30) -> list:
    """
    统计高频词（双字词和三字词），排除常见虚词和人名提示词。
    返回 [(词, 频次), ...] 按频次降序。
    """
    # 停用词（常见虚词、连词等）
    stopwords = set([
        "的", "了", "是", "在", "我", "他", "她", "它", "你", "们",
        "这", "那", "有", "和", "与", "也", "都", "就", "但", "而",
        "不", "没", "对", "把", "被", "让", "给", "从", "到", "向",
        "会", "能", "可", "要", "想", "说", "看", "走", "来", "去",
        "上", "下", "里", "外", "前", "后", "中", "啊", "吧", "呢",
        "吗", "嗯", "哦", "哈", "呀", "哎", "哇", "哼", "唉",
        "一个", "一下", "一声", "一眼", "一步", "一时", "一种",
        "什么", "怎么", "为什么", "一样", "这样", "那样", "如此",
    ])

    # 提取所有连续汉字片段（2-4字）
    candidates = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    # 过滤停用词
    filtered = [w for w in candidates if w not in stopwords]
    counter = Counter(filtered)

    # 只保留频次>=3的词
    result = [(word, count) for word, count in counter.most_common(top_n) if count >= 3]
    return result


def detect_repetition(text: str) -> dict:
    """
    检测重复问题：
    1. 单句重复（同义短句）
    2. 高频短语（特定词组）
    """
    paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 10]

    # 检测段落间的相似性（简化版：检查相同长度区间内的共同词汇比例）
    similar_pairs = []
    for i in range(len(paragraphs)):
        for j in range(i + 1, min(i + 5, len(paragraphs))):  # 只比较相邻5段
            p1 = set(re.findall(r"[\u4e00-\u9fff]{2,4}", paragraphs[i]))
            p2 = set(re.findall(r"[\u4e00-\u9fff]{2,4}", paragraphs[j]))
            if not p1 or not p2:
                continue
            overlap = len(p1 & p2) / min(len(p1), len(p2))
            if overlap > 0.6 and len(paragraphs[i]) > 20:  # 60%词汇重叠且段落不太短
                similar_pairs.append({
                    "para_index_1": i + 1,
                    "para_index_2": j + 1,
                    "similarity": round(overlap, 2),
                    "para_1_preview": paragraphs[i][:40] + "...",
                    "para_2_preview": paragraphs[j][:40] + "...",
                })

    # 检测高频重复短语（3字以上且出现3次+）
    phrase_candidates = re.findall(r"[\u4e00-\u9fff]{3,8}", text)
    phrase_counter = Counter(phrase_candidates)
    repeated_phrases = [
        {"phrase": phrase, "count": count}
        for phrase, count in phrase_counter.most_common(20)
        if count >= 3
    ]

    return {
        "similar_paragraph_pairs": similar_pairs[:10],  # 最多报告10对
        "high_freq_phrases": repeated_phrases[:15],
    }


def detect_ai_patterns(text: str) -> dict:
    """
    检测AI写作特征词和句式模式。
    返回命中的特征词、句式，以及AI痕迹综合评分。
    """
    hits = []

    # 检测特征词组（精确匹配）
    for pattern_word in AI_PATTERN_WORDS:
        count = text.count(pattern_word)
        if count > 0:
            hits.append({
                "type": "特征词组",
                "pattern": pattern_word,
                "count": count,
            })

    # 检测简单高频词（出现次数超过阈值才报告）
    total_chars = len(re.sub(r"\s", "", text))
    threshold = max(2, total_chars // 500)  # 每500字出现2次以上才报警
    for word in AI_HIGH_FREQ_SIMPLE:
        count = text.count(word)
        if count > threshold:
            hits.append({
                "type": "高频修饰词",
                "pattern": word,
                "count": count,
                "threshold": threshold,
            })

    # 检测结构性正则模式
    for pattern in AI_STRUCTURE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            hits.append({
                "type": "结构模板",
                "pattern": pattern,
                "count": len(matches),
                "examples": [m if isinstance(m, str) else m[0] for m in matches[:3]],
            })

    # 根据命中数量给出AI痕迹等级
    hit_count = len(hits)
    if hit_count == 0:
        ai_level = "无明显AI痕迹"
        score_hint = "9-10"
    elif hit_count <= 2:
        ai_level = "轻微AI痕迹"
        score_hint = "7-8"
    elif hit_count <= 5:
        ai_level = "中度AI痕迹"
        score_hint = "5-6"
    elif hit_count <= 9:
        ai_level = "重度AI痕迹"
        score_hint = "3-4"
    else:
        ai_level = "极重AI痕迹"
        score_hint = "1-2"

    return {
        "ai_level": ai_level,
        "score_hint": score_hint,
        "hit_count": hit_count,
        "hits": hits,
    }


def analyze_paragraph_structure(text: str) -> dict:
    """
    分析段落结构特征：
    - 段落长度分布
    - 是否有连续流水账段落
    - 对话比例
    - 纯动作句检测
    """
    paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 5]
    if not paragraphs:
        return {"error": "无有效段落"}

    lengths = [len(p) for p in paragraphs]

    # 检测流水账段落（段落内无感官描写词）
    sensory_words = ["看", "听", "闻", "触", "感", "感觉", "觉得", "像", "如同",
                     "仿佛", "似乎", "光", "声", "味", "气息", "温度", "冷", "热",
                     "软", "硬", "香", "腥", "亮", "暗", "响", "静"]
    emotion_words = ["高兴", "悲伤", "愤怒", "恐惧", "惊讶", "厌恶", "喜欢", "害怕",
                     "紧张", "放松", "期待", "失望", "后悔", "骄傲", "羞耻", "内疚",
                     "心", "情", "感"]

    flowing_water_count = 0
    for p in paragraphs:
        has_sensory = any(w in p for w in sensory_words)
        has_emotion = any(w in p for w in emotion_words)
        # 简单的流水账判定：段落较长，但缺乏感官/情感词
        if len(p) > 50 and not has_sensory and not has_emotion:
            flowing_water_count += 1

    # 对话比例
    dialog_chars = len(re.findall(r"[「『"（【].*?[」』"）】]", text))
    dialog_ratio = round(dialog_chars / max(len(text), 1), 3)

    # 检测均匀段落（AI特征）
    if len(lengths) >= 4:
        avg_len = sum(lengths) / len(lengths)
        # 计算标准差
        variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
        std_dev = variance ** 0.5
        uniformity_score = round(std_dev / avg_len, 2) if avg_len > 0 else 0
        # uniformity_score 越低，段落越均匀（AI特征越明显）
        is_uniform = uniformity_score < 0.3
    else:
        uniformity_score = None
        is_uniform = False

    # 检测句长均质化（AI特征：连续5句以上长度在15-30字之间且波动<5字）
    sentences = re.split(r"[。！？…]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) >= 5]
    sentence_lengths = [len(s) for s in sentences]
    sentence_uniformity = False
    if len(sentence_lengths) >= 5:
        for i in range(len(sentence_lengths) - 4):
            window = sentence_lengths[i:i+5]
            window_max = max(window)
            window_min = min(window)
            if 15 <= window_min and window_max <= 30 and (window_max - window_min) <= 5:
                sentence_uniformity = True
                break

    # 检测"的的不休"（单句中出现>=4个"的"字）
    de_overuse = []
    for i, p in enumerate(paragraphs):
        for sent in re.split(r"[。！？…，；]", p):
            if sent.strip() and sent.count("的") >= 4:
                de_overuse.append({"para": i+1, "text": sent.strip()[:50] + ("..." if len(sent.strip()) > 50 else "")})
                if len(de_overuse) >= 5:
                    break

    return {
        "paragraph_count": len(paragraphs),
        "length_distribution": {
            "avg": round(sum(lengths) / len(lengths), 1),
            "max": max(lengths),
            "min": min(lengths),
            "short_paras": sum(1 for l in lengths if l < 30),
            "long_paras": sum(1 for l in lengths if l > 200),
        },
        "flowing_water_paragraphs": flowing_water_count,
        "dialog_ratio": dialog_ratio,
        "paragraph_uniformity": {
            "std_dev_ratio": uniformity_score,
            "is_suspiciously_uniform": is_uniform,
            "note": "段落长度变化系数低于0.3时疑似AI生成（段落过于均匀）" if is_uniform else "段落长度分布正常",
        },
        "sentence_uniformity": sentence_uniformity,
        "sentence_uniformity_note": "⚠️ 连续5句以上长度高度一致（15-30字，波动≤5字），疑似AI节奏均质化" if sentence_uniformity else "句长变化正常",
        "de_overuse": de_overuse,
        "de_overuse_note": f"⚠️ 发现{len(de_overuse)}处'的'字密集（单句≥4个'的'）" if de_overuse else "'的'字使用正常",
    }


# ──────────────────────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────────────────────

def format_report(results: dict) -> str:
    """将分析结果格式化为可读的文本报告。"""
    lines = []
    lines.append("=" * 60)
    lines.append("网文文本统计分析报告")
    lines.append("=" * 60)

    if "basic" in results:
        b = results["basic"]
        lines.append("\n【基础统计】")
        lines.append(f"  总字数（不含空白）: {b['total_chars']:,}")
        lines.append(f"  段落数: {b['paragraph_count']}")
        lines.append(f"  句子数（估算）: {b['sentence_count']}")
        lines.append(f"  平均段落长度: {b['avg_para_length']} 字")
        lines.append(f"  最长段落: {b['max_para_length']} 字")
        lines.append(f"  最短段落: {b['min_para_length']} 字")

    if "structure" in results:
        s = results["structure"]
        lines.append("\n【段落结构分析】")
        dist = s["length_distribution"]
        lines.append(f"  段落数: {s['paragraph_count']}")
        lines.append(f"  平均长度: {dist['avg']} 字 | 最长: {dist['max']} 字 | 最短: {dist['min']} 字")
        lines.append(f"  短段落（<30字）: {dist['short_paras']} 个")
        lines.append(f"  长段落（>200字）: {dist['long_paras']} 个")
        lines.append(f"  疑似流水账段落: {s['flowing_water_paragraphs']} 个")
        lines.append(f"  对话占比（估算）: {s['dialog_ratio']*100:.1f}%")
        uni = s["paragraph_uniformity"]
        flag = "⚠️ " if uni["is_suspiciously_uniform"] else "✓ "
        lines.append(f"  {flag}段落均匀度: {uni['note']}")
        lines.append(f"  {'⚠️ ' if s['sentence_uniformity'] else '✓ '}{s['sentence_uniformity_note']}")
        lines.append(f"  {s['de_overuse_note']}")
        if s["de_overuse"]:
            for item in s["de_overuse"][:3]:
                lines.append(f"    第{item['para']}段: \"{item['text']}\"")

    if "ai" in results:
        ai = results["ai"]
        lines.append("\n【AI痕迹检测】")
        level_icon = {"无明显AI痕迹": "✓", "轻微AI痕迹": "△", "中度AI痕迹": "⚠️",
                      "重度AI痕迹": "✗", "极重AI痕迹": "✗✗"}.get(ai["ai_level"], "?")
        lines.append(f"  {level_icon} AI痕迹等级: {ai['ai_level']}（评分参考: {ai['score_hint']}）")
        lines.append(f"  命中特征数: {ai['hit_count']}")
        if ai["hits"]:
            lines.append("  命中特征详情:")
            for hit in ai["hits"][:20]:
                if hit["type"] == "结构模板" and "examples" in hit:
                    lines.append(f"    [{hit['type']}] \"{hit['examples'][0] if hit['examples'] else hit['pattern']}\" × {hit['count']}")
                else:
                    lines.append(f"    [{hit['type']}] \"{hit['pattern']}\" × {hit['count']}")

    if "repeat" in results:
        r = results["repeat"]
        lines.append("\n【重复雷同检测】")
        if r["similar_paragraph_pairs"]:
            lines.append(f"  ⚠️  发现 {len(r['similar_paragraph_pairs'])} 对疑似雷同段落:")
            for pair in r["similar_paragraph_pairs"][:5]:
                lines.append(f"    第{pair['para_index_1']}段 ↔ 第{pair['para_index_2']}段（相似度 {pair['similarity']*100:.0f}%）")
                lines.append(f"      段{pair['para_index_1']}: {pair['para_1_preview']}")
                lines.append(f"      段{pair['para_index_2']}: {pair['para_2_preview']}")
        else:
            lines.append("  ✓  未发现明显的段落雷同")

        if r["high_freq_phrases"]:
            lines.append(f"  高频短语 Top 10:")
            for item in r["high_freq_phrases"][:10]:
                lines.append(f"    \"{item['phrase']}\" × {item['count']}")

    if "word_freq" in results:
        lines.append("\n【词频统计 Top 20】")
        for word, count in results["word_freq"][:20]:
            lines.append(f"  {word}: {count} 次")

    lines.append("\n" + "=" * 60)
    lines.append("分析完成。以上数据供 novel-audit 审计参考使用。")
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="网文文本统计分析工具（novel-audit 辅助脚本）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", help="要分析的文本文件路径")
    parser.add_argument(
        "--mode",
        choices=["full", "repeat", "ai", "structure", "basic"],
        default="full",
        help="分析模式（默认: full）",
    )
    parser.add_argument("--json", action="store_true", help="输出JSON格式（供程序调用）")
    args = parser.parse_args()

    text = load_text(args.file)

    results = {}

    if args.mode in ("full", "basic"):
        results["basic"] = basic_stats(text)

    if args.mode in ("full", "structure"):
        results["structure"] = analyze_paragraph_structure(text)

    if args.mode in ("full", "ai"):
        results["ai"] = detect_ai_patterns(text)

    if args.mode in ("full", "repeat"):
        results["repeat"] = detect_repetition(text)
        results["word_freq"] = word_frequency(text, top_n=30)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_report(results))


if __name__ == "__main__":
    main()
