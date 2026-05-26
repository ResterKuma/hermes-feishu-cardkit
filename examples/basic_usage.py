"""
feishu-cardkit 使用示例。
"""

import asyncio
import lark_oapi as lark
from feishu_cardkit import (
    CardBuilder,
    StreamingCardController,
    create_streaming_card,
    send_progress_card,
)


# ── 示例 1：用构建器创建卡片 JSON ──────────────────────────────

def example_builder():
    """演示 CardBuilder 的用法。"""
    card = (
        CardBuilder()
        .header("项目进度", template="blue", subtitle="本周更新")
        .markdown("**任务完成率：85%**\n\n一切顺利 ✅")
        .table_from_markdown(
            "| 名称 | 状态 | 负责人 |\n"
            "|------|------|--------|\n"
            "| 前端 | ✅ | 小明 |\n"
            "| 后端 | 🔄 | 小红 |"
        )
        .hr()
        .collapsible_panel("🛠️ 详情", [
            {"tag": "markdown", "content": "步骤1: 初始化 ✓", "text_size": "notation"},
            {"tag": "markdown", "content": "步骤2: 执行 ✓", "text_size": "notation"},
        ])
        .note("最后更新: 2026-05-26")
        .build()
    )

    import json
    print(json.dumps(card, indent=2, ensure_ascii=False))


# ── 示例 2：流式卡片 ─────────────────────────────────────────

async def example_streaming():
    """演示流式卡片的创建和更新。"""
    # 替换为你的实际凭据
    client = lark.Client.builder() \
        .app_id("cli_xxx") \
        .app_secret("xxx") \
        .build()

    ctrl = await create_streaming_card(
        client,
        chat_id="oc_xxx",
        header_title="🤖 AI 助手",
        header_template="blue",
    )

    # 模拟流式输出
    words = ["你好", "你好，", "你好，世界", "你好，世界！"]
    for w in words:
        await ctrl.update_content(w, is_partial=True)
        await asyncio.sleep(0.3)

    # 添加工具调用步骤
    await ctrl.add_tool_step("search", title="搜索数据库", status="running")
    await asyncio.sleep(0.5)
    await ctrl.update_tool_step(0, status="completed", summary="找到 3 条结果")

    # 最终完成
    await ctrl.finalize(text="你好，世界！")


# ── 示例 3：进度卡片 ─────────────────────────────────────────

async def example_progress():
    """演示进度通知卡片。"""
    client = lark.Client.builder() \
        .app_id("cli_xxx") \
        .app_secret("xxx") \
        .build()

    msg_id = await send_progress_card(
        client,
        chat_id="oc_xxx",
        title="数据处理中",
        progress_text="正在处理第 3/10 批数据...",
        progress_percent=30,
        status="Running",
    )
    print(f"进度卡片已发送: {msg_id}")


if __name__ == "__main__":
    print("=== CardBuilder 示例 ===")
    example_builder()

    # 异步示例需要实际飞书凭据，这里仅做展示
    # asyncio.run(example_streaming())
    # asyncio.run(example_progress())
