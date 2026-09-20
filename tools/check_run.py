#!/usr/bin/env python3
"""一条命令判断「刚才那次飞书指令走到哪一环」。

用法：sudo /opt/anki-autocards/venv/bin/python /opt/anki-autocards/docs/deploy/check_run.py

输出四行 + 结论，不用人肉翻日志。
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, "/opt/anki-autocards")
from anki.collection import Collection  # noqa: E402

BASE_NOTES = 3641          # 2026-09-20 基线
HOME = "/home/hermes/.hermes"
AGENT_LOG = f"{HOME}/logs/agent.log"
SEEN = f"{HOME}/feishu_seen_message_ids.json"


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=30).stdout
    except Exception as e:
        return f"(取不到: {e})"


def main():
    print("=" * 64)
    print("飞书 → Anki 试车自检")
    print("=" * 64)

    # ① 收到消息了吗
    try:
        d = json.load(open(SEEN))
        ids = d.get("message_ids") or {}
        newest = max(ids.values()) if ids else 0
        ago = (time.time() - newest) / 60 if newest else -1
        print(f"\n① 收到消息：共 {len(ids)} 条"
              + (f"，最新一条 {ago:.0f} 分钟前" if ago >= 0 else ""))
        got_msg = ago >= 0 and ago < 60
        print(f"   最近 1 小时有新消息：{'是' if got_msg else '否'}")
    except Exception as e:
        print(f"\n① 收到消息：读不到 —— {e}")
        got_msg = None

    # ② 起回合了吗
    tail = sh(f"sudo tail -3000 {AGENT_LOG} 2>/dev/null")
    lines = [l for l in tail.splitlines() if l.strip()]
    # 只看最近 60 分钟 —— 不然会把几小时前的 cron 旧账也算进来
    cutoff = time.time() - 3600
    recent = []
    for l in lines:
        if "mem_trim" in l:
            continue
        # 只有行首是时间戳的才算一条日志；
        # 栈回溯的续行（File "..."、raise ...）没有时间戳，跳过 ——
        # 否则会把几小时前的回溯当成"刚刚发生"
        if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", l):
            continue
        try:
            ts = time.mktime(time.strptime(l[:19], "%Y-%m-%d %H:%M:%S"))
        except Exception:
            continue
        if ts >= cutoff:
            recent.append(l)
    non_hb = recent
    print(f"\n② 起回合：最近 60 分钟里非心跳 {len(non_hb)} 行")
    if non_hb:
        print("   最后 3 条：")
        for l in non_hb[-3:]:
            print("     " + l[:110])
    turned = len(non_hb) > 0

    # ③ 碰到 Anki 了吗
    # 注意：agent.log 只记「工具被调用了」，不记调用内容，
    # 所以这一项经常是 0 —— 不能拿它当判据，只能当参考
    hits = sh(f"sudo grep -icE 'anki|制卡|生活摘录' {AGENT_LOG} 2>/dev/null").strip()
    try:
        hits_n = int(hits.splitlines()[0])
    except Exception:
        hits_n = 0
    print(f"\n③ 碰到 Anki：日志命中 {hits_n} 次（仅供参考，工具内容不进日志）")

    # ④ 写进去了吗
    col = Collection("/var/lib/anki-autocards/collection.anki2")
    try:
        notes = col.db.scalar("select count() from notes")
        delta = notes - BASE_NOTES
        print(f"\n④ 写进去了：notes {BASE_NOTES} → {notes}（+{delta}）")
        if delta > 0:
            dn = {d["id"]: d["name"] for d in col.decks.all()}
            rows = col.db.execute(
                "select id from notes order by id desc limit %d" % delta)
            print("   最近新增：")
            for (nid,) in rows:
                n = col.get_note(nid)
                deck = "?"
                if n.cards():
                    deck = dn.get(n.cards()[0].did, "?")
                body = (n["正文"] if "正文" in n else "").replace("\n", " ")[:46]
                print(f"     · [{deck}] {body}")
    finally:
        col.close()

    # 结论
    print("\n" + "=" * 64)
    # 判据优先级：④ 写没写进去 > ② 起没起回合 > ① 收没收到
    # ③ 不能当判据（工具内容不进日志）—— 之前就是它导致误报「断在 ④」
    if delta > 0:
        print(f"结论：✅ 全通。写了 {delta} 张，去 Anki 里看卡片长什么样")
        if not got_msg:
            print("      （① 没检测到新消息，可能是消息 id 被清理过，以 ④ 为准）")
    elif not turned:
        print("结论：断在 ②—— 没起回合。查 gateway → 会话派发")
    elif got_msg is False:
        print("结论：还没收到新指令（或消息没到 gateway）。")
        print("      先确认你在飞书里发过了；发了还是这样 → 查 systemctl / gateway_state.json")
    else:
        print("结论：断在 ⑥—— 起了回合但没写进去。去会话里看返回的 failed / skipped")
    print("=" * 64)


if __name__ == "__main__":
    main()
