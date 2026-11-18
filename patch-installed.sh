#!/bin/sh
# 给「已安装」的微信读书打补丁（推荐方案：不动 APK、不重签名）
#
# 原理：Waydroid 安装 APK 时会把 native 库解压到
#   ~/.local/share/waydroid/data/app/~~<hash>/<pkg>-<hash>/lib/<abi>/
# 我们只把 libmoai-sqlite.so 里的 ashmem_set_prot_region 改成「直接返回 0」，
# APK 签名保持腾讯原厂，离线书解密 / 微信登录都不会受影响。
#
# 用法：
#   waydroid app install ~/Downloads/weread.apk      # 先正常安装原包
#   ./patch-installed.sh com.tencent.weread           # 再打补丁
#   # 升级后重新执行一次 ./patch-installed.sh <包名>
set -e
PKG=${1:-com.tencent.weread}
HERE=$(cd "$(dirname "$0")" && pwd)
BASE="$HOME/.local/share/waydroid/data/app"

found=0
for d in "$BASE"/~~*/"$PKG"-*/lib/*/; do
    [ -f "$d/libmoai-sqlite.so" ] || continue
    found=1
    python3 "$HERE/tools/patch_so.py" "$d/libmoai-sqlite.so"
done

if [ "$found" = 0 ]; then
    echo "没找到 $PKG 的 libmoai-sqlite.so" >&2
    echo "确认包名/是否已安装：waydroid app list | grep -A2 $PKG" >&2
    exit 1
fi

echo
echo "提示：如果 App 正在运行，先 waydroid app launch 重新拉起（或 waydroid session stop && waydroid session start）"
