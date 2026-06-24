#!/usr/bin/env bash
# 检测本地 Chrome 已安装的 profiles，帮助用户选择已登录 BOSS 的那个
# Usage: bash chrome-profile.sh
set -euo pipefail

CHROME_DIR="$HOME/Library/Application Support/Google/Chrome"

if [ ! -d "$CHROME_DIR" ]; then
    echo "ERROR: Chrome 目录不存在: $CHROME_DIR"
    exit 1
fi

echo "检测到以下 Chrome Profiles:"
echo ""

LOCAL_STATE="$CHROME_DIR/Local State"
count=0

for dir in "$CHROME_DIR"/Profile* "$CHROME_DIR"/Default; do
    [ -d "$dir" ] || continue
    profile_name=$(basename "$dir")
    
    display_name=""
    if [ -f "$LOCAL_STATE" ] && command -v python3 &>/dev/null; then
        display_name=$(python3 -c "
import json, sys
try:
    with open('$LOCAL_STATE') as f:
        state = json.load(f)
    info = state.get('profile', {}).get('info_cache', {}).get('$profile_name', {})
    print(info.get('name', ''))
except: pass
" 2>/dev/null || true)
    fi
    
    has_zhipin=false
    if [ -d "$dir/Local Storage" ] || [ -d "$dir/Cookies" ]; then
        if [ -f "$dir/Cookies" ] && strings "$dir/Cookies" 2>/dev/null | grep -q "zhipin"; then
            has_zhipin=true
        fi
    fi
    
    count=$((count + 1))
    if [ -n "$display_name" ]; then
        echo "  [$count] $profile_name - \"$display_name\"${has_zhipin:+ ⭐ 检测到BOSS登录痕迹}"
    else
        echo "  [$count] $profile_name${has_zhipin:+ ⭐ 检测到BOSS登录痕迹}"
    fi
done

echo ""
echo "请选择已登录BOSS直聘的profile编号，然后按以下方式使用："
echo "  agent-browser --profile \"<完整路径>\" open ..."
echo ""
echo "示例："
echo "  agent-browser --profile \"$CHROME_DIR/Default\" open https://www.zhipin.com/web/geek/job"
