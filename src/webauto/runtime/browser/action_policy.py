"""Semantic risk classification for reversible browser interaction tools."""

from __future__ import annotations

from typing import Any

APPROVAL_REQUIRED_MARKER = "WEBAUTO_APPROVAL_REQUIRED"
HUMAN_REQUIRED_MARKER = "WEBAUTO_HUMAN_REQUIRED"

_SEARCH_MARKERS = (
    "搜索",
    "查询",
    "查找",
    "search",
    "find",
)

_EXTERNAL_WRITE_MARKERS = (
    "提交订单",
    "确认订单",
    "确认下单",
    "立即购买",
    "去支付",
    "确认支付",
    "支付",
    "付款",
    "转账",
    "充值",
    "加入购物车",
    "添加购物车",
    "收藏",
    "关注",
    "点赞",
    "投票",
    "发布",
    "上架",
    "确认发布",
    "发送消息",
    "发送",
    "回复",
    "删除",
    "移除",
    "下架",
    "改价",
    "退款",
    "确认收货",
    "确认交易",
    "保存",
    "保存修改",
    "确定",
    "确认",
    "预约",
    "报名",
    "订阅",
    "place order",
    "buy now",
    "checkout",
    "pay now",
    "confirm payment",
    "add to cart",
    "publish",
    "post listing",
    "send message",
    "submit form",
    "delete",
    "remove listing",
    "refund",
    "confirm receipt",
    "subscribe",
    "save",
    "confirm",
)

_SENSITIVE_INPUT_MARKERS = (
    "password",
    "passwd",
    "密码",
    "cvv",
    "cvc",
    "card number",
    "credit card",
    "银行卡",
    "卡号",
    "支付密码",
    "验证码",
    "verification code",
    "one-time code",
    "otp",
)


_PAYMENT_CLICK_MARKERS = (
    "去支付",
    "确认支付",
    "支付",
    "付款",
    "pay now",
    "confirm payment",
)


def interaction_preview(node: Any) -> dict[str, Any]:
    attributes = {
        str(key): str(value) for key, value in (getattr(node, "attributes", None) or {}).items()
    }
    text_method = getattr(node, "get_meaningful_text_for_llm", None)
    text = str(text_method() if callable(text_method) else "").strip()
    if not text:
        text = str(getattr(node, "node_value", "") or "").strip()
    ax_node = getattr(node, "ax_node", None)
    ax_name = str(getattr(ax_node, "name", "") or "").strip()
    return {
        "tag": str(getattr(node, "tag_name", "") or getattr(node, "node_name", "")).lower(),
        "text": text[:300],
        "accessible_name": ax_name[:300],
        "attributes": {
            key: value[:300]
            for key, value in attributes.items()
            if key
            in {
                "type",
                "role",
                "name",
                "id",
                "title",
                "aria-label",
                "placeholder",
                "autocomplete",
            }
        },
    }


def click_requires_approval(node: Any) -> tuple[bool, dict[str, Any]]:
    preview = interaction_preview(node)
    values = [preview["text"], preview["accessible_name"]]
    values.extend(preview["attributes"].values())
    semantic = " ".join(values).lower()
    if any(marker in semantic for marker in _EXTERNAL_WRITE_MARKERS):
        return True, preview
    input_type = preview["attributes"].get("type", "").lower()
    if input_type == "submit" and not any(marker in semantic for marker in _SEARCH_MARKERS):
        return True, preview
    # B1-03: any button-like element without identifiable text or accessible name
    # is treated as an unknown external-write target and requires approval
    # (per plan §17.3 "Unknown 默认 L2"; previously None leaked through).
    text = preview["text"].strip()
    aria = preview["accessible_name"].strip()
    if not text and not aria and preview["tag"] in {"button", "a", "img", "input"}:
        return True, preview
    return False, preview


def external_write_operation(preview: dict[str, Any]) -> str | None:
    values = [
        str(preview.get("text", "")),
        str(preview.get("accessible_name", "")),
    ]
    values.extend(str(value) for value in preview.get("attributes", {}).values())
    semantic = " ".join(values).lower()
    if any(marker in semantic for marker in _PAYMENT_CLICK_MARKERS):
        return "payment"
    if any(marker in semantic for marker in ("加入购物车", "添加购物车", "add to cart")):
        return "add_to_cart"
    if any(marker in semantic for marker in ("立即购买", "buy now", "checkout", "去结算")):
        return "start_checkout"
    if any(marker in semantic for marker in ("提交订单", "确认订单", "确认下单", "place order")):
        return "place_order"
    if any(
        marker in semantic for marker in ("确认发布", "发布", "上架", "publish", "post listing")
    ):
        return "xianyu_publish"
    if any(marker in semantic for marker in ("下架", "remove listing")):
        return "xianyu_downlist"
    if any(marker in semantic for marker in ("改价", "修改价格", "保存价格")):
        return "xianyu_update_price"
    if any(marker in semantic for marker in ("发送消息", "发送", "回复", "send message")):
        return "xianyu_send_message"
    if any(
        marker in semantic
        for marker in (
            "删除",
            "退款",
            "确认收货",
            "转账",
            "delete",
            "refund",
            "transfer",
        )
    ):
        return "prohibited"
    return None


def input_requires_human(node: Any) -> tuple[bool, dict[str, Any]]:
    preview = interaction_preview(node)
    values = [preview["text"], preview["accessible_name"]]
    values.extend(preview["attributes"].values())
    semantic = " ".join(values).lower()
    input_type = preview["attributes"].get("type", "").lower()
    autocomplete = preview["attributes"].get("autocomplete", "").lower()
    sensitive = input_type == "password" or autocomplete.startswith("cc-")
    return sensitive or any(marker in semantic for marker in _SENSITIVE_INPUT_MARKERS), preview


__all__ = [
    "APPROVAL_REQUIRED_MARKER",
    "HUMAN_REQUIRED_MARKER",
    "click_requires_approval",
    "external_write_operation",
    "input_requires_human",
    "interaction_preview",
]
