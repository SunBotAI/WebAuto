#!/usr/bin/env python3
"""凭证库密钥迁移工具.

用法:
    python Tools/migrate_secrets.py                          # 交互式
    GLM_GRABBER_KEY=xxx python Tools/migrate_secrets.py     # 非交互

功能:
    1. 用 GLM_GRABBER_KEY 解密 .secrets.enc
    2. 备份原文件到 .secrets.enc.bak
    3. 用 WEBAUTO_MASTER_KEY（或自动生成的 key）重新加密保存
    4. 验证解密成功

环境变量:
    WEBAUTO_MASTER_KEY: 直接的 Fernet key（优先）
    GLM_GRABBER_KEY:   老用户口令（必须有，用于解密）
    SECRETS_PATH:      凭证文件路径（默认 .secrets.enc）
    AUTO_KEY_PATH:     自动生成的 key 路径（默认 ~/.webauto_master.key）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Zhipu.crypto import (
    CryptoError,
    WEBAUTO_KEY_ENV,
    LEGACY_KEY_ENV,
    _AUTO_KEY_PATH,
    _get_fernet_key,
    load_legacy,
    SecretStore,
)


def main():
    parser = argparse.ArgumentParser(description="凭证库密钥迁移工具")
    parser.add_argument(
        "--secrets", default=".secrets.enc",
        help=f"凭证文件路径（默认 .secrets.enc）"
    )
    parser.add_argument(
        "--no-backup", action="store_true",
        help="跳过备份（默认会备份为 .bak）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只验证能否解密，不写入新文件"
    )
    args = parser.parse_args()

    secrets_path = Path(args.secrets)
    print(f"=== 凭证迁移工具 ===")
    print(f"凭证文件: {secrets_path}")
    print(f"WEBAUTO_MASTER_KEY: {'已设置' if os.environ.get(WEBAUTO_KEY_ENV) else '未设置（将自动生成）'}")
    print(f"GLM_GRABBER_KEY:   {'已设置' if os.environ.get(LEGACY_KEY_ENV) else '未设置！'}")
    print()

    # 检查文件是否存在
    if not secrets_path.exists():
        print(f"❌ 文件不存在: {secrets_path}")
        print("  无需迁移（可能是全新的空凭证库）")
        sys.exit(0)

    blob = secrets_path.read_bytes()
    if not blob:
        print("❌ 文件为空，无需迁移")
        sys.exit(0)

    # 1. 尝试用 GLM_GRABBER_KEY 解密
    print("▶ 步骤1: 用 GLM_GRABBER_KEY 解密...")
    data = load_legacy(secrets_path)
    if data is None:
        print(f"❌ 解密失败：请确认设置了 {LEGACY_KEY_ENV} 环境变量")
        sys.exit(1)
    accounts = data.get("accounts", [])
    print(f"  ✅ 解密成功，共 {len(accounts)} 个账号")
    for a in accounts:
        print(f"    - {a.get('name', '?')} ({a.get('phone', '?')})")

    if args.dry_run:
        print("\n[dry-run] 验证通过，不写入新文件")
        sys.exit(0)

    # 2. 备份
    if not args.no_backup:
        bak = secrets_path.with_suffix(secrets_path.suffix + ".bak")
        import shutil
        shutil.copy2(secrets_path, bak)
        print(f"\n▶ 步骤2: 已备份到 {bak}")

    # 3. 用新 key 保存
    print(f"\n▶ 步骤3: 用 {WEBAUTO_KEY_ENV} 重新加密...")
    store = SecretStore(secrets_path)
    store.save(data)
    print(f"  ✅ 已保存到 {secrets_path}")

    # 4. 验证
    print(f"\n▶ 步骤4: 验证解密...")
    verify = store.load()
    if verify.get("accounts") == data.get("accounts"):
        print(f"  ✅ 验证通过，{len(verify.get('accounts', []))} 个账号")
    else:
        print(f"  ❌ 验证失败！数据不匹配！")
        sys.exit(1)

    # 提示
    new_key = os.environ.get(WEBAUTO_KEY_ENV)
    if new_key:
        print(f"\n✅ 迁移完成！")
    else:
        auto_key = _AUTO_KEY_PATH.read_bytes() if _AUTO_KEY_PATH.exists() else None
        if auto_key:
            print(f"\n✅ 迁移完成！自动生成的 key 已保存到 {_AUTO_KEY_PATH}")
            print(f"\n⚠️  建议将以下内容加入 ~/.bashrc 或 ~/.zshrc:")
            print(f"   export {WEBAUTO_KEY_ENV}=$(cat {_AUTO_KEY_PATH})")


if __name__ == "__main__":
    main()
