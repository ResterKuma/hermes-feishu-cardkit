#!/usr/bin/env bash
# feishu-cardkit installer — 一键安装到 Hermes Agent
# 用法: curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash
#
# 功能: 将 CardKit 流式卡片控制器安装到 Hermes 的 gateway/platforms/ 目录
# 安装后 Hermes 直接 from gateway.platforms.feishu_cardkit import ... 即可使用

set -e

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "🃏 feishu-cardkit installer for Hermes Agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. 查找 Hermes 安装路径 ──
HERMES_PATH=""

# 方法1: 通过 which/hermes 命令查找
if command -v hermes &>/dev/null; then
    HERMES_BIN="$(readlink -f "$(which hermes)" 2>/dev/null || which hermes)"
    # hermes 通常在 ~/.hermes/hermes-agent/venv/bin/hermes 或类似路径
    if [[ "$HERMES_BIN" == *".hermes"* ]]; then
        # 从 bin/hermes 反推项目根目录
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

# 方法3: 通过 pip 查找 hermes-agent 包
if [ -z "$HERMES_PATH" ]; then
    PIP_PATH=$(python3 -c "import gateway; print(gateway.__file__)" 2>/dev/null | sed 's|/gateway/__init__.*||')
    if [ -d "$PIP_PATH/gateway/platforms" ]; then
        HERMES_PATH="$PIP_PATH"
    fi
fi

# 找不到则报错
if [ -z "$HERMES_PATH" ] || [ ! -d "$HERMES_PATH/gateway/platforms" ]; then
    echo -e "${RED}❌ 未找到 Hermes Agent 安装路径${NC}"
    echo ""
    echo "请手动指定路径:"
    echo "  bash install.sh --path /path/to/hermes-agent"
    echo ""
    echo "或设置环境变量:"
    echo "  HERMES_PATH=/path/to/hermes-agent bash install.sh"
    exit 1
fi

PLATFORMS_DIR="$HERMES_PATH/gateway/platforms"
echo -e "${GREEN}✅ 找到 Hermes:${NC} $HERMES_PATH"

# ── 2. 处理命令行参数 ──
while [[ $# -gt 0 ]]; do
    case $1 in
        --path)
            HERMES_PATH="$2"
            PLATFORMS_DIR="$HERMES_PATH/gateway/platforms"
            shift 2
            ;;
        --uninstall)
            echo "🗑️  卸载 feishu_cardkit..."
            rm -f "$PLATFORMS_DIR/feishu_cardkit.py"
            echo -e "${GREEN}✅ 已卸载${NC}"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# ── 3. 下载 hermes_controller.py ──
TARGET="$PLATFORMS_DIR/feishu_cardkit.py"
GITHUB_RAW="https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/src/feishu_cardkit/hermes_controller.py"

echo -e "${YELLOW}⬇️  下载 CardKit 控制器...${NC}"

if curl --version &>/dev/null; then
    DL_CMD="curl -fsSL"
elif wget --version &>/dev/null; then
    DL_CMD="wget -qO -"
else
    echo -e "${RED}❌ 需要 curl 或 wget${NC}"
    exit 1
fi

# 备份已有文件
if [ -f "$TARGET" ]; then
    BACKUP="$TARGET.bak.$(date +%Y%m%d%H%M%S)"
    cp "$TARGET" "$BACKUP"
    echo -e "${YELLOW}📦 已备份旧版本:${NC} $BACKUP"
fi

# 下载
$DL_CMD "$GITHUB_RAW" > "$TARGET"

if [ ! -s "$TARGET" ]; then
    echo -e "${RED}❌ 下载失败${NC}"
    # 恢复备份
    if [ -n "$BACKUP" ] && [ -f "$BACKUP" ]; then
        mv "$BACKUP" "$TARGET"
        echo -e "${YELLOW}↩️  已恢复备份${NC}"
    fi
    exit 1
fi

# ── 4. 验证 ──
LINE_COUNT=$(wc -l < "$TARGET")
SIZE=$(wc -c < "$TARGET")

echo ""
echo -e "${GREEN}✅ 安装成功！${NC}"
echo -e "   文件: ${TARGET}"
echo -e "   大小: ${SIZE} bytes / ${LINE_COUNT} lines"
echo ""
echo "📝 在 Hermes 中使用:"
echo "   from gateway.platforms.feishu_cardkit import StreamingCardController"
echo ""
echo "🗑️  卸载:"
echo "   curl -fsSL https://raw.githubusercontent.com/ResterKuma/hermes-feishu-cardkit/main/install.sh | bash -s -- --uninstall"
echo ""
