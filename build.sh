#!/usr/bin/env bash
# ===========================================================================
# bidding_etl Linux 可执行文件构建脚本
# 环境要求: Python 3.8 + pip
# 用法: chmod +x build.sh && ./build.sh
# 输出: dist/bidding_etl (Linux ELF 可执行文件)
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " bidding_etl - Linux 可执行文件构建"
echo "========================================"

# 1. 检查 Python 版本（3.8+）
PYTHON=""
echo "[检查] 搜索 Python 3.8+..."

for cmd in python3 python python3.12 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$cmd" &>/dev/null 2>&1; then
        ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
        if [[ "$ver" =~ ^3\.(8|9|10|11|12)$ ]]; then
            PYTHON="$cmd"
            echo "[Python] 找到: $cmd (版本 $ver)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[错误] 未找到 Python 3.8+，请先安装:"
    echo ""
    echo "  ┌─ Ubuntu / Debian ──────────────────────────┐"
    echo "  │  sudo apt update                           │"
    echo "  │  sudo apt install python3 python3-venv     │"
    echo "  │  sudo apt install python3.8 python3.8-venv │"
    echo "  └────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─ RHEL 7（推荐：IUS 仓库）──────────────────┐"
    echo "  │  sudo yum install -y epel-release          │"
    echo "  │  sudo yum install -y https://repo.ius.io/  │"
    echo "  │                    ius-release-el7.rpm     │"
    echo "  │  sudo yum install -y python38              │"
    echo "  │  sudo yum install -y python38-pip          │"
    echo "  │  sudo yum install -y python38-devel        │"
    echo "  └────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─ CentOS / RHEL 8+ ─────────────────────────┐"
    echo "  │  sudo yum install python3 python3-devel     │"
    echo "  └────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─ 任意系统 ─ 用 pyenv（无需 sudo）──────────┐"
    echo "  │  curl https://pyenv.run | bash             │"
    echo "  │  pyenv install 3.8.18                      │"
    echo "  │  pyenv local 3.8.18   # 在项目目录下运行  │"
    echo "  └────────────────────────────────────────────┘"
    exit 1
fi

# 2. 创建并激活虚拟环境
VENV_DIR="$SCRIPT_DIR/build_venv"
if [ -d "$VENV_DIR" ]; then
    echo "[清理] 移除旧的虚拟环境..."
    rm -rf "$VENV_DIR"
fi

echo "[虚拟环境] 创建中..."
"$PYTHON" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
echo "[虚拟环境] 已激活: $("$PYTHON" --version)"

# 3. 升级 pip
echo "[pip] 升级 pip..."
"$PYTHON" -m pip install --upgrade pip -q

# 4. 安装项目依赖
echo "[依赖] 安装项目依赖..."
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" --no-cache-dir

# 5. 用 PyInstaller 打包
echo ""
echo "========================================"
echo " 开始打包..."
echo "========================================"

# 清理旧的构建产物
rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist"
rm -f "$SCRIPT_DIR"/*.spec

"$PYTHON" -m PyInstaller \
    --onefile \
    --name "bidding_etl" \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    --specpath "$SCRIPT_DIR" \
    --add-data "$SCRIPT_DIR/requirements.txt:." \
    --hidden-import "trino" \
    --hidden-import "trino.auth" \
    --hidden-import "trino.dbapi" \
    --hidden-import "pandas" \
    --hidden-import "PyPDF2" \
    --hidden-import "docx" \
    --hidden-import "pkg_resources.py2_warn" \
    --collect-all "trino" \
    --collect-all "pandas" \
    "$SCRIPT_DIR/bidding_etl.py"

# 6. 验证构建结果
echo ""
echo "========================================"
echo " 验证打包结果"
echo "========================================"
EXE_PATH="$SCRIPT_DIR/dist/bidding_etl"
if [ -f "$EXE_PATH" ]; then
    FILE_SIZE=$(du -h "$EXE_PATH" | cut -f1)
    echo "[成功] 可执行文件已生成: $EXE_PATH"
    echo "[大小] $FILE_SIZE"
    file "$EXE_PATH"
else
    echo "[错误] 打包失败，未找到输出文件"
    exit 1
fi

# 7. 清理临时文件
echo ""
echo "[清理] 移除临时构建文件..."
rm -rf "$SCRIPT_DIR/build"
rm -rf "$SCRIPT_DIR/__pycache__"
rm -f "$SCRIPT_DIR/bidding_etl.spec"

# 8. 退出虚拟环境
deactivate
echo "[完成] 虚拟环境已退出"

echo ""
echo "========================================"
echo " 构建完成!"
echo " 输出文件: $EXE_PATH"
echo " 使用方法:"
echo "   ./dist/bidding_etl"
echo "========================================"
