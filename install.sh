#!/usr/bin/env bash
# feishu-cardkit v2 installer — 一键安装到 Hermes Agent
# 用法: curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash
#
# 功能:
#   1. 将 feishu_cardkit.py 安装到 gateway/platforms/
#   2. 将 cardkit_stream_consumer.py 安装到 gateway/
#   3. Patch gateway/run.py 和 gateway/platforms/feishu.py 中的联动代码
#
# 定位: Hermes Agent 专用插件，不做通用适配

set -e

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "🃏 feishu-cardkit v2 — Hermes Agent 专用插件"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. 查找 Hermes 安装路径 ──
HERMES_PATH=""

# 方法1: 通过 which hermes 命令查找
if command -v hermes &>/dev/null; then
    HERMES_BIN="$(readlink -f "$(which hermes)" 2>/dev/null || which hermes)"
    if [[ "$HERMES_BIN" == *".hermes"* ]]; then
        HERMES_PATH="$(echo "$HERMES_BIN" | sed 's|/venv/bin/.*||; s|/bin/.*||')"
    fi
fi

# 方法2: 检查常见路径
if [ -z "$HERMES_PATH" ]; then
    for candidate in \
        "$HOME/.hermes/hermes-agent" \
        "$HOME/.local/share/hermes/hermes-agent" \
        "$HOME/hermes/hermes-agent"; do
        if [ -d "$candidate/gateway/platforms" ]; then
            HERMES_PATH="$candidate"
            break
        fi
    done
fi

# 方法3: 通过 pip 查找
if [ -z "$HERMES_PATH" ]; then
    PIP_PATH=$(python3 -c "import gateway; print(gateway.__file__)" 2>/dev/null | sed 's|/gateway/__init__.*||')
    if [ -d "$PIP_PATH/gateway/platforms" ]; then
        HERMES_PATH="$PIP_PATH"
    fi
fi

if [ -z "$HERMES_PATH" ] || [ ! -d "$HERMES_PATH/gateway/platforms" ]; then
    echo -e "${RED}❌ 未找到 Hermes Agent 安装路径${NC}"
    echo ""
    echo "请手动指定路径:"
    echo "  bash install.sh --path /path/to/hermes-agent"
    echo ""
    exit 1
fi

PLATFORMS_DIR="$HERMES_PATH/gateway/platforms"
GATEWAY_DIR="$HERMES_PATH/gateway"
echo -e "${GREEN}✅ 找到 Hermes:${NC} $HERMES_PATH"

# ── 2. 处理命令行参数 ──
UNINSTALL=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --path)
            HERMES_PATH="$2"
            PLATFORMS_DIR="$HERMES_PATH/gateway/platforms"
            GATEWAY_DIR="$HERMES_PATH/gateway"
            shift 2
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

if $UNINSTALL; then
    echo "🗑️  卸载 feishu-cardkit v2..."
    rm -f "$PLATFORMS_DIR/feishu_cardkit.py"
    rm -f "$GATEWAY_DIR/cardkit_stream_consumer.py"
    # 注意: run.py 和 feishu.py 的 patch 不会被自动回退
    echo -e "${YELLOW}⚠️  文件已删除，但 gateway/run.py 和 feishu.py 的联动代码未回退${NC}"
    echo "   如需完全回退，请手动还原以下文件:"
    echo "      $GATEWAY_DIR/run.py"
    echo "      $PLATFORMS_DIR/feishu.py"
    echo -e "${GREEN}✅ 卸载完成${NC}"
    exit 0
fi

# ── 3. 检查下载工具 ──
if command -v curl &>/dev/null; then
    DL_CMD="curl -fsSL"
elif command -v wget &>/dev/null; then
    DL_CMD="wget -qO -"
else
    echo -e "${RED}❌ 需要 curl 或 wget${NC}"
    exit 1
fi

GITHUB_RAW="https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main"

# ── 4. 安装 feishu_cardkit.py ──
CARDKIT_TARGET="$PLATFORMS_DIR/feishu_cardkit.py"
echo -e "${YELLOW}⬇️  下载 feishu_cardkit.py (CardKit v2 最终版)...${NC}"

if [ -f "$CARDKIT_TARGET" ]; then
    BACKUP="$CARDKIT_TARGET.bak.$(date +%Y%m%d%H%M%S)"
    cp "$CARDKIT_TARGET" "$BACKUP"
    echo -e "${YELLOW}📦 已备份旧版本:${NC} $BACKUP"
fi

$DL_CMD "$GITHUB_RAW/src/feishu_cardkit/feishu_cardkit.py" > "$CARDKIT_TARGET"

if [ ! -s "$CARDKIT_TARGET" ]; then
    echo -e "${RED}❌ 下载 feishu_cardkit.py 失败${NC}"
    if [ -n "$BACKUP" ] && [ -f "$BACKUP" ]; then
        mv "$BACKUP" "$CARDKIT_TARGET"
        echo -e "${YELLOW}↩️  已恢复备份${NC}"
    fi
    exit 1
fi

echo -e "${GREEN}   ✅ feishu_cardkit.py ($(wc -l < "$CARDKIT_TARGET") lines)${NC}"

# ── 5. 安装 cardkit_stream_consumer.py ──
CONSUMER_TARGET="$GATEWAY_DIR/cardkit_stream_consumer.py"
echo -e "${YELLOW}⬇️  下载 cardkit_stream_consumer.py...${NC}"

if [ -f "$CONSUMER_TARGET" ]; then
    BACKUP2="$CONSUMER_TARGET.bak.$(date +%Y%m%d%H%M%S)"
    cp "$CONSUMER_TARGET" "$BACKUP2"
    echo -e "${YELLOW}📦 已备份旧版本:${NC} $BACKUP2"
fi

$DL_CMD "$GITHUB_RAW/src/feishu_cardkit/cardkit_stream_consumer.py" > "$CONSUMER_TARGET"

if [ ! -s "$CONSUMER_TARGET" ]; then
    echo -e "${RED}❌ 下载 cardkit_stream_consumer.py 失败${NC}"
    if [ -n "$BACKUP2" ] && [ -f "$BACKUP2" ]; then
        mv "$BACKUP2" "$CONSUMER_TARGET"
    fi
    exit 1
fi

echo -e "${GREEN}   ✅ cardkit_stream_consumer.py ($(wc -l < "$CONSUMER_TARGET") lines)${NC}"

# ── 6. Patch gateway/run.py ──
RUN_PY="$GATEWAY_DIR/run.py"
echo -e "${YELLOW}🔧 检查 gateway/run.py 联动代码...${NC}"

if [ -f "$RUN_PY" ]; then
    # 检查 CardKit import 是否已经存在
    if grep -q "from gateway.cardkit_stream_consumer import CardKitStreamConsumer" "$RUN_PY"; then
        echo -e "${GREEN}   ✅ run.py 已包含 CardKit 联动代码，无需修改${NC}"
    else
        echo -e "${RED}   ⚠️  run.py 未包含 CardKit 联动代码${NC}"
        echo "      请手动添加以下内容到 run.py 中 (参考 README 安装说明):"
        echo ""
        echo "  在 _run_agent 方法中 (约 13120 行附近):"
        echo "    from gateway.cardkit_stream_consumer import CardKitStreamConsumer, CardKitStreamConsumerConfig"
        echo ""
        echo -e "${YELLOW}   ⚠️  自动 patch 跳过，请手动完成${NC}"
    fi
else
    echo -e "${RED}   ⚠️  未找到 $RUN_PY${NC}"
fi

# ── 7. Patch gateway/platforms/feishu.py ──
FEISHU_PY="$PLATFORMS_DIR/feishu.py"
echo -e "${YELLOW}🔧 检查 gateway/platforms/feishu.py 联动代码...${NC}"

if [ -f "$FEISHU_PY" ]; then
    if grep -q "from gateway.platforms.feishu_cardkit import" "$FEISHU_PY" && \
       grep -q "CARDKIT_AVAILABLE" "$FEISHU_PY"; then
        echo -e "${GREEN}   ✅ feishu.py 已包含 CardKit 联动代码${NC}"
    else
        echo -e "${RED}   ⚠️  feishu.py 未包含完整 CardKit 联动代码${NC}"
        echo "      请手动添加 (参考 README 安装说明)"
    fi
else
    echo -e "${RED}   ⚠️  未找到 $FEISHU_PY${NC}"
fi

# ── 8. 完成 ──
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ 安装成功！${NC}"
echo ""
echo "📦 已安装文件:"
echo "   $CARDKIT_TARGET"
echo "   $CONSUMER_TARGET"
echo ""
echo "🔧 重启 Hermes Gateway 使配置生效:"
echo "   hermes gateway restart"
echo "   或 (如果通过 systemd):"
echo "   sudo systemctl restart hermes-gateway"
echo ""
echo "📝 在 hermes/config.yaml 中启用流式卡片:"
echo "   platforms:"
echo "     feishu:"
echo "       cardkit_streaming_enabled: true"
echo ""
echo "🗑️  卸载:"
echo "   curl -fsSL $GITHUB_RAW/install.sh | bash -s -- --uninstall"
echo ""
