"""
CardKit API 封装。

提供对飞书 CardKit REST API 的 Python async 封装，包括：
- 创建卡片实体
- 发送卡片消息
- 流式更新内容
- 完整替换卡片
- 增量补丁元素
- 开启/关闭流式模式
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("feishu_cardkit.api")

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        ReplyMessageRequest,
        ReplyMessageRequestBody,
    )
    from lark_oapi.api.cardkit.v1.model import (
        CreateCardRequest,
        CreateCardRequestBody,
        ContentCardElementRequest,
        ContentCardElementRequestBody,
        CreateCardElementRequest,
        CreateCardElementRequestBody,
        DeleteCardElementRequest,
        DeleteCardElementRequestBody,
        UpdateCardElementRequest,
        UpdateCardElementRequestBody,
        PatchCardElementRequest,
        PatchCardElementRequestBody,
        UpdateCardRequest,
        UpdateCardRequestBody,
        SettingsCardRequest,
        SettingsCardRequestBody,
    )
    LARK_AVAILABLE = True
except ImportError:
    LARK_AVAILABLE = False
    lark = None


class CardKitAPI:
    """飞书 CardKit API 封装。

    封装了 CardKit 和 IM 消息相关 API，提供简洁的 async 接口。

    Args:
        client: ``lark_oapi.Client`` 实例。

    示例::

        import lark_oapi as lark
        from feishu_cardkit import CardKitAPI

        client = lark.Client.builder() \\
            .app_id("cli_xxx") \\
            .app_secret("xxx") \\
            .build()

        api = CardKitAPI(client)
        card_id = await api.create_card(card_json)
        await api.send_card_message(card_id, "oc_xxx")
    """

    def __init__(self, client: Any) -> None:
        if not LARK_AVAILABLE:
            raise ImportError(
                "lark_oapi 未安装，请运行: pip install lark-oapi"
            )
        self.client = client

    # ── 卡片实体 ────────────────────────────────────────────

    async def create_card(self, card: Dict[str, Any]) -> Optional[str]:
        """创建 CardKit 卡片实体。

        Args:
            card: Card JSON 2.0 字典。

        Returns:
            成功返回 card_id，失败返回 None。
        """
        try:
            request = (
                CreateCardRequest.builder()
                .request_body(
                    CreateCardRequestBody.builder()
                    .type("card_json")
                    .data(json.dumps(card))
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(self.client.cardkit.v1.card.create, request),
                timeout=10.0,
            )

            if response.code == 0:
                card_id = (
                    response.data.card_id
                    if hasattr(response, "data") and response.data
                    else None
                )
                if card_id:
                    logger.info("创建卡片实体: %s", card_id)
                    return card_id
            else:
                logger.warning(
                    "创建卡片失败: code=%s, msg=%s", response.code, response.msg
                )
        except asyncio.TimeoutError:
            logger.warning("创建卡片超时 (10s)")
        except Exception as e:
            logger.error("创建卡片异常: %s", e)

        return None

    # ── 发送消息 ────────────────────────────────────────────

    async def send_card_message(
        self,
        card_id: str,
        chat_id: str,
        *,
        reply_to: Optional[str] = None,
        reply_in_thread: bool = False,
    ) -> Optional[Dict[str, str]]:
        """发送引用 CardKit 卡片的 IM 消息。

        Args:
            card_id: 卡片实体 ID。
            chat_id: 目标聊天 ID。
            reply_to: 回复的消息 ID（可选）。
            reply_in_thread: 是否在话题中回复。

        Returns:
            成功返回 ``{"message_id": ..., "chat_id": ...}``，失败返回 None。
        """
        content_payload = json.dumps({
            "type": "card",
            "data": {"card_id": card_id},
        })

        try:
            if reply_to:
                request = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_to)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(content_payload)
                        .msg_type("interactive")
                        .reply_in_thread(reply_in_thread)
                        .build()
                    )
                    .build()
                )
                response = await asyncio.wait_for(
                    asyncio.to_thread(self.client.im.v1.message.reply, request),
                    timeout=10.0,
                )
            else:
                request = (
                    CreateMessageRequest.builder()
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id)
                        .content(content_payload)
                        .msg_type("interactive")
                        .build()
                    )
                    .receive_id_type("chat_id")
                    .build()
                )
                response = await asyncio.wait_for(
                    asyncio.to_thread(self.client.im.v1.message.create, request),
                    timeout=10.0,
                )

            if hasattr(response, "data") and response.data:
                result = {
                    "message_id": getattr(response.data, "message_id", ""),
                    "chat_id": getattr(response.data, "chat_id", ""),
                }
                logger.info("发送卡片消息: %s", result["message_id"])
                return result

        except asyncio.TimeoutError:
            logger.warning("发送卡片消息超时 (10s)")
        except Exception as e:
            logger.error("发送卡片消息异常: %s", e)

        return None

    # ── 流式更新 ────────────────────────────────────────────

    async def stream_content(
        self, card_id: str, element_id: str, content: str, sequence: int
    ) -> bool:
        """流式更新卡片元素内容（打字机效果）。

        Args:
            card_id: 卡片实体 ID。
            element_id: 目标元素 ID。
            content: 新内容文本。
            sequence: 序列号（递增）。
        """
        try:
            request = (
                ContentCardElementRequest.builder()
                .card_id(card_id)
                .element_id(element_id)
                .request_body(
                    ContentCardElementRequestBody.builder()
                    .content(content)
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.cardkit.v1.card_element.content, request
                ),
                timeout=10.0,
            )

            if response.code == 0:
                return True
            else:
                logger.warning(
                    "流式更新失败: code=%s, msg=%s", response.code, response.msg
                )
        except asyncio.TimeoutError:
            logger.warning("流式更新超时 (10s)")
        except Exception as e:
            logger.error("流式更新异常: %s", e)

        return False

    # ── 完整更新 ────────────────────────────────────────────

    async def update_card(
        self, card_id: str, card: Dict[str, Any], sequence: int
    ) -> bool:
        """完整替换卡片内容。

        Args:
            card_id: 卡片实体 ID。
            card: 新的 Card JSON 2.0 字典。
            sequence: 序列号（递增）。
        """
        try:
            request = (
                UpdateCardRequest.builder()
                .card_id(card_id)
                .request_body(
                    UpdateCardRequestBody.builder()
                    .card({"type": "card_json", "data": json.dumps(card)})
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(self.client.cardkit.v1.card.update, request),
                timeout=10.0,
            )

            if response.code == 0:
                return True
            else:
                logger.warning(
                    "更新卡片失败: code=%s, msg=%s", response.code, response.msg
                )
        except asyncio.TimeoutError:
            logger.warning("更新卡片超时 (10s)")
        except Exception as e:
            logger.error("更新卡片异常: %s", e)

        return False

    # ── 增量补丁 ────────────────────────────────────────────

    async def patch_element(
        self,
        card_id: str,
        element_id: str,
        partial: Dict[str, Any],
        sequence: int,
    ) -> bool:
        """增量更新单个卡片元素。

        比 :meth:`update_card` 更轻量，只更新变化的部分。

        Args:
            card_id: 卡片实体 ID。
            element_id: 目标元素 ID。
            partial: 部分元素数据。
            sequence: 序列号。
        """
        try:
            request = (
                PatchCardElementRequest.builder()
                .card_id(card_id)
                .element_id(element_id)
                .request_body(
                    PatchCardElementRequestBody.builder()
                    .partial_element(json.dumps(partial))
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.cardkit.v1.card_element.patch, request
                ),
                timeout=10.0,
            )

            if response.code == 0:
                return True
            else:
                logger.warning(
                    "补丁元素失败: code=%s, msg=%s", response.code, response.msg
                )
        except asyncio.TimeoutError:
            logger.warning("补丁元素超时 (10s)")
        except Exception as e:
            logger.error("补丁元素异常: %s", e)

        return False

    # ── 流式模式 ────────────────────────────────────────────

    async def set_streaming_mode(
        self, card_id: str, enabled: bool, sequence: int
    ) -> bool:
        """开启或关闭卡片的流式模式。

        Args:
            card_id: 卡片实体 ID。
            enabled: True 开启，False 关闭。
            sequence: 序列号。
        """
        try:
            request = (
                SettingsCardRequest.builder()
                .card_id(card_id)
                .request_body(
                    SettingsCardRequestBody.builder()
                    .settings(json.dumps({"streaming_mode": enabled}))
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(self.client.cardkit.v1.card.settings, request),
                timeout=10.0,
            )

            if response.code == 0:
                return True
            else:
                logger.warning(
                    "设置流式模式失败: code=%s, msg=%s",
                    response.code,
                    response.msg,
                )
        except asyncio.TimeoutError:
            logger.warning("设置流式模式超时 (10s)")
        except Exception as e:
            logger.error("设置流式模式异常: %s", e)

        return False

    # ── 组件级 CRUD ─────────────────────────────────────────

    async def create_element(
        self,
        card_id: str,
        element: Dict[str, Any],
        *,
        after_element_id: Optional[str] = None,
        sequence: int,
    ) -> bool:
        """在卡片中添加新组件。

        Args:
            card_id: 卡片实体 ID。
            element: 新组件 JSON 字典。
            after_element_id: 插入到哪个元素之后（None=末尾 append）。
            sequence: 序列号。
        """
        try:
            insert_type = "insert_after" if after_element_id else "append"
            builder = (
                CreateCardElementRequestBody.builder()
                .type(insert_type)
                .elements(json.dumps([element]))
                .sequence(sequence)
            )
            if after_element_id:
                builder.target_element_id(after_element_id)

            request = (
                CreateCardElementRequest.builder()
                .card_id(card_id)
                .request_body(builder.build())
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.cardkit.v1.card_element.create, request
                ),
                timeout=10.0,
            )

            if response.code == 0:
                logger.info("添加组件成功")
                return True
            else:
                logger.warning(
                    "添加组件失败: code=%s, msg=%s", response.code, response.msg
                )
        except asyncio.TimeoutError:
            logger.warning("添加组件超时 (10s)")
        except Exception as e:
            logger.error("添加组件异常: %s", e)

        return False

    async def delete_element(
        self,
        card_id: str,
        element_id: str,
        *,
        sequence: int,
    ) -> bool:
        """删除卡片中的指定组件。

        Args:
            card_id: 卡片实体 ID。
            element_id: 要删除的元素 ID。
            sequence: 序列号。
        """
        try:
            request = (
                DeleteCardElementRequest.builder()
                .card_id(card_id)
                .element_id(element_id)
                .request_body(
                    DeleteCardElementRequestBody.builder()
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.cardkit.v1.card_element.delete, request
                ),
                timeout=10.0,
            )

            if response.code == 0:
                logger.info("删除组件成功: %s", element_id)
                return True
            else:
                logger.warning(
                    "删除组件失败: code=%s, msg=%s", response.code, response.msg
                )
        except asyncio.TimeoutError:
            logger.warning("删除组件超时 (10s)")
        except Exception as e:
            logger.error("删除组件异常: %s", e)

        return False

    async def update_element(
        self,
        card_id: str,
        element_id: str,
        element: Dict[str, Any],
        *,
        sequence: int,
    ) -> bool:
        """完整更新卡片中的指定组件（比 patch 更彻底）。

        Args:
            card_id: 卡片实体 ID。
            element_id: 要更新的元素 ID。
            element: 新的完整元素 JSON。
            sequence: 序列号。
        """
        try:
            request = (
                UpdateCardElementRequest.builder()
                .card_id(card_id)
                .element_id(element_id)
                .request_body(
                    UpdateCardElementRequestBody.builder()
                    .element(json.dumps(element))
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.cardkit.v1.card_element.update, request
                ),
                timeout=10.0,
            )

            if response.code == 0:
                logger.info("更新组件成功: %s", element_id)
                return True
            else:
                logger.warning(
                    "更新组件失败: code=%s, msg=%s", response.code, response.msg
                )
        except asyncio.TimeoutError:
            logger.warning("更新组件超时 (10s)")
        except Exception as e:
            logger.error("更新组件异常: %s", e)

        return False
