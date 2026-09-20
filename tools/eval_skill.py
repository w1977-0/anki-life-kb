#!/usr/bin/env python3
"""技能评估（evals）—— 改完技能跑一次，确认没退化。

官方要求：至少 3 个评估，改一次跑一次，基于观察而不是假设。
这里覆盖**确定性那层**（脚本的推导与校验），因为它能被自动验证；
模型的判断（判类型、定牌组）靠真实对话观察，不在这里。

用法：
  sudo /opt/anki-autocards/venv/bin/python /opt/anki-autocards/docs/deploy/eval_skill.py

除了最后一条，全部用 --dry-run，**不写库、可重复跑**。
"""
import json
import subprocess
import sys

SCRIPT = "/home/hermes/.hermes/skills/note-taking/anki-cards/scripts/anki_add.py"
PY = "/opt/anki-autocards/venv/bin/python"
BOOK = "30：读过::30.01：书::30.01.01：《纳瓦尔宝典》"
INBOX = "00：系统::00.02：收件箱"

passed, failed = 0, 0


def run(args):
    p = subprocess.run([PY, SCRIPT] + args, capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}  —— {detail}")


def dry(deck, type_, body="测试正文", **kw):
    """跑 dry-run 并解析出 JSON。布尔旗（True/False）只传旗名。"""
    args = ["--deck", deck, "--type", type_, "--body", body,
            "--source", "《测试》", "--dry-run"]
    for k, v in kw.items():
        flag = f"--{k.replace('_', '-')}"
        if isinstance(v, bool):
            if v:
                args.append(flag)
        else:
            args += [flag, str(v)]
    code, out = run(args)
    i = out.find("{")
    data = json.loads(out[i:]) if i >= 0 else None
    return code, out, data


print("=" * 62)
print("anki-cards 技能评估")
print("=" * 62)

# ── E1 观点 → 回忆 ────────────────────────────────────────
print("\n【E1】类型=观点 → 应走「回忆」（自测=自测），版式在 gezhi/paper/kaiwu 里")
code, out, d = dry(BOOK, "观点")
f = d["cards"][0]["fields"] if d else {}
check("退出码 0", code == 0, out[:120])
check("自测 = 自测（回忆）", f.get("自测") == "自测", repr(f.get("自测")))
check("版式 ∈ 观点池", f.get("风格") in ("gezhi", "paper", "kaiwu"), repr(f.get("风格")))
check("7 个字段齐全", len(f) == 7, f"{len(f)} 个")

# ── E2 句子 → 通读 ────────────────────────────────────────
print("\n【E2】类型=句子 → 应走「通读」（自测留空），版式在 memo/kaiwu/paper 里")
code, out, d = dry(BOOK, "句子")
f = d["cards"][0]["fields"] if d else {}
check("退出码 0", code == 0, out[:120])
check("自测 留空（通读）", f.get("自测") == "", repr(f.get("自测")))
check("版式 ∈ 句子池", f.get("风格") in ("memo", "kaiwu", "paper"), repr(f.get("风格")))

# ── E3 类型写错 ───────────────────────────────────────────
print("\n【E3】类型写错 → 应拦下并列出十个值")
code, out, _ = dry(BOOK, "金句")
check("退出码 2", code == 2, str(code))
check("提示里列出十个值", "不在十个值里" in out, out[:120])
check("提示指向 references", "类型与版式" in out, out[:120])

# ── E4 牌组写错 ───────────────────────────────────────────
print("\n【E4】牌组写错 → 应拦下（不能静默建野牌组）")
code, out, _ = dry("C：文章保存并提炼", "句子")
check("退出码 2", code == 2, str(code))
check("提示牌组不存在", "不存在" in out, out[:120])
check("给出收件箱兜底", INBOX in out, out[:120])

# ── E5 版式写错 ───────────────────────────────────────────
print("\n【E5】版式写错 → 应拦下")
code, out, _ = dry(BOOK, "句子", skin="paperr")
check("退出码 2", code == 2, str(code))
check("提示版式无效", "无效" in out, out[:120])

# ── E6 正文过长提醒 ───────────────────────────────────────
print("\n【E6】正文超 150 字 → 应提醒拆分但不拦死")
code, out, d = dry(BOOK, "句子", body="字" * 200)
check("退出码 0（不拦死）", code == 0, str(code))
check("有拆分提醒", "150 字上限" in out, out[:120])

# ── E7 \n\n → 自动转 <p> ────────────────────────────────────
print("\n【E7】正文用 \\n\\n 分段 → 应自动包成 <p>")
code, out, d = dry(BOOK, "句子", body="第一段。\n\n第二段。")
f = d["cards"][0]["fields"] if d else {}
check("退出码 0", code == 0, out[:120])
check("正文含 <p>", "<p>" in f.get("正文", ""), repr(f.get("正文", ""))[:80])

# ── E8 --whole：长文不拦 + 强制 paper + 标签 ─────────────
print("\n【E8】--whole 整篇保留 → 长文不拦、强制 paper、自动加「完整保留」标签")
code, out, d = dry(BOOK, "句子", body="字" * 300, whole=True)
f = d["cards"][0]["fields"] if d else {}
tags = d["cards"][0].get("tags", []) if d else []
check("退出码 0（不拦长文）", code == 0, str(code))
check("版式强制 paper", f.get("风格") == "paper", f"实际 {f.get('风格')}")
check("标签含「完整保留」", "完整保留" in tags, str(tags))

# ── E9 长文类型 → 通读 + 只用 paper ──────────────────────
print("\n【E9】类型=长文 → 应通读（自测空）、版式 paper、不受 150 字限制")
code, out, d = dry(BOOK, "长文", body="字" * 5000)
f = d["cards"][0]["fields"] if d else {}
check("退出码 0（长文不被拦）", code == 0, out[:120])
check("自测 留空（通读）", f.get("自测") == "", repr(f.get("自测")))
check("版式 = paper", f.get("风格") == "paper", f"实际 {f.get('风格')}")

# ── E10 出处占位符 → 应拦下 ───────────────────────────────
print("\n【E10】出处是占位符（一句话/未知/无）→ 应拦下")
code, out, _ = dry(BOOK, "句子", source="一句话")
check("退出码 2", code == 2, str(code))
check("提示要写真来源", "占位符" in out, out[:120])
check("给出「网络」兜底", "网络" in out, out[:120])

print("\n" + "=" * 62)
print(f"通过 {passed}，失败 {failed}")
print("=" * 62)
sys.exit(1 if failed else 0)