#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
API密钥加密解密工具

一个简单的API密钥加密解密工具，使用AES-GCM加密算法。
通过菜单选择功能，可以轻松加密或解密API密钥。
"""

import os
import sys
import time
from ruamel.yaml import YAML

# 动态调整sys.path以支持打包和直接运行
try:
    # 打包后（sys.frozen）或直接运行时，将项目根目录添加到sys.path
    if getattr(sys, "frozen", False):
        # 如果是打包后的应用
        project_root = os.path.dirname(sys.executable)
    else:
        # 如果是直接运行的.py文件
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 现在可以使用绝对路径导入
    from utils.api_crypto import encrypt_api_key, decrypt_api_key
    from core.config_management import get_models_config_file_path

except ImportError as e:
    print(f"导入错误: {e}")
    print("无法加载核心模块。请确保在项目根目录下运行，或检查依赖项是否完整。")
    print(f"当前sys.path: {sys.path}")
    input("按回车键退出...")
    sys.exit(1)


def clear_screen() -> None:
    """清空控制台屏幕"""
    os.system("cls" if os.name == "nt" else "clear")


def print_color(text: str, color: str | None = None) -> None:
    """带颜色打印文本

    颜色选项: green, red, yellow, blue, purple, cyan
    """
    colors = {
        "green": "\033[92m",
        "red": "\033[91m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "purple": "\033[95m",
        "cyan": "\033[96m",
        "end": "\033[0m",
    }

    if color and color in colors:
        print(f"{colors[color]}{text}{colors['end']}")
    else:
        print(text)


def show_menu() -> str:
    """显示主菜单"""
    clear_screen()
    print("=" * 60)
    print_color(" API密钥加密解密工具 v3.0", "cyan")
    print_color(" (仅支持V2格式)", "yellow")
    print("=" * 60)
    print("\n请选择操作:")
    print_color(" 1. 加密API密钥", "green")
    print_color(" 2. 解密API密钥 (仅V2格式)", "blue")
    print_color(" 3. 为特定提供商设置API密钥", "purple")
    print_color(" 4. 退出程序", "yellow")
    print("\n" + "=" * 60)
    return input("\n请输入选项 (1-4): ").strip()


def encrypt_api_key_menu() -> None:
    """加密API密钥菜单"""
    clear_screen()
    print("=" * 60)
    print_color(" 加密API密钥", "green")
    print_color(" (将使用V2格式加密)", "yellow")
    print("=" * 60)

    api_key = input("\n请输入要加密的API密钥: ").strip()
    if not api_key:
        print_color("\nAPI密钥不能为空!", "red")
        input("按回车返回主菜单...")
        return

    use_custom_password = input("\n是否使用自定义密码? (y/n, 默认n): ").strip().lower()
    password = None

    if use_custom_password == "y":
        password = input("请输入自定义密码: ").strip()
        if not password:
            print_color("未输入密码，将使用默认密码", "yellow")
            password = None

    print_color("\n正在加密...", "cyan")
    sys.stdout.flush()  # 确保立即显示
    time.sleep(0.5)  # 短暂延迟，增强体验

    result = encrypt_api_key(api_key, password)

    print("\n加密结果:")
    print("-" * 60)
    print_color(result, "purple")
    print("-" * 60)
    print("\n可以将此加密结果复制到config.yaml文件中的api_key字段")
    print("此密钥已采用V2格式加密，可用于v2.1.5+版本的翻译工具")

    input("\n按回车返回主菜单...")


def set_provider_api_key() -> None:
    """为特定提供商设置API密钥"""
    clear_screen()
    print("=" * 60)
    print_color(" 为特定提供商设置API密钥", "purple")
    print_color(" (将使用V2格式加密并保存到models.yaml)", "yellow")
    print("=" * 60)

    # 获取models.yaml文件路径
    # 直接使用导入的常量
    models_config_file = get_models_config_file_path()

    # 检查models.yaml文件是否存在
    if not os.path.exists(models_config_file):
        print_color(f"models.yaml文件不存在: {models_config_file}", "red")
        print("请先确保models.yaml文件存在。")
        input("按回车返回主菜单...")
        return

    # 读取现有的models.yaml文件
    try:
        yaml_loader = YAML()
        with open(models_config_file, "r", encoding="utf-8-sig") as f:
            models_config = yaml_loader.load(f)
        if models_config is None:
            models_config = {}
    except Exception as e:
        print_color(f"读取models.yaml文件失败: {e}", "red")
        input("按回车返回主菜单...")
        return

    # 显示当前可用的提供商
    if models_config:
        print("\n当前配置中的提供商:")
        for provider in models_config.keys():
            print(f"  - {provider}")
    else:
        print("\n当前models.yaml文件中没有配置任何提供商。")

    # 询问用户要为哪个提供商设置API密钥
    provider_name = input("\n请输入要设置API密钥的提供商名称: ").strip()
    if not provider_name:
        print_color("提供商名称不能为空!", "red")
        input("按回车返回主菜单...")
        return

    # 检查提供商是否存在于配置中
    if provider_name not in models_config:
        # 如果提供商不存在，询问用户是否要添加
        add_provider = (
            input(
                f"提供商 '{provider_name}' 不存在于当前配置中，是否要添加? (y/n, 默认n): "
            )
            .strip()
            .lower()
        )
        if add_provider != "y":
            print("取消操作。")
            input("按回车返回主菜单...")
            return
        # 添加新的提供商
        models_config[provider_name] = {
            "api_key": "",
            "api_base": "",
            "api_mode": "openai",  # 默认值
            "models": [],
        }

    # 询问用户输入API密钥
    api_key = input(f"\n请输入 {provider_name} 的API密钥: ").strip()
    if not api_key:
        print_color("API密钥不能为空!", "red")
        input("按回车返回主菜单...")
        return

    # 询问是否使用自定义密码
    use_custom_password = input("\n是否使用自定义密码? (y/n, 默认n): ").strip().lower()
    password = None

    if use_custom_password == "y":
        password = input("请输入自定义密码: ").strip()
        if not password:
            print_color("未输入密码，将使用默认密码", "yellow")
            password = None

    # 加密API密钥
    print_color("\n正在加密API密钥...", "cyan")
    sys.stdout.flush()  # 确保立即显示
    time.sleep(0.5)  # 短暂延迟，增强体验

    encrypted_api_key = encrypt_api_key(api_key, password)
    if not encrypted_api_key:
        print_color("API密钥加密失败!", "red")
        input("按回车返回主菜单...")
        return

    # 更新提供商的api_key字段
    models_config[provider_name]["api_key"] = encrypted_api_key

    # 保存更新后的models.yaml文件
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(models_config_file), exist_ok=True)

        # 保存文件
        with open(models_config_file, "w", encoding="utf-8-sig") as f:
            yaml_loader.dump(models_config, f)

        print("\nAPI密钥已成功设置并保存到models.yaml文件中。")
        print_color(f"提供商: {provider_name}", "green")
        print_color(f"加密后的API密钥: {encrypted_api_key}", "purple")
    except Exception as e:
        print_color(f"保存models.yaml文件失败: {e}", "red")
        input("按回车返回主菜单...")
        return

    input("\n按回车返回主菜单...")


def decrypt_api_key_menu() -> None:
    """解密API密钥菜单"""
    clear_screen()
    print("=" * 60)
    print_color(" 解密API密钥", "blue")
    print_color(" (仅支持V2格式)", "yellow")
    print("=" * 60)

    encrypted_api_key = input("\n请输入要解密的API密钥: ").strip()
    if not encrypted_api_key:
        print_color("\n加密的API密钥不能为空!", "red")
        input("按回车返回主菜单...")
        return

    use_custom_password = input("\n是否使用自定义密码? (y/n, 默认n): ").strip().lower()
    password = None

    if use_custom_password == "y":
        password = input("请输入自定义密码: ").strip()
        if not password:
            print_color("未输入密码，将使用默认密码", "yellow")
            password = None

    print_color("\n正在解密...", "cyan")
    sys.stdout.flush()  # 确保立即显示
    time.sleep(0.5)  # 短暂延迟，增强体验

    result = decrypt_api_key(encrypted_api_key, password)

    print("\n解密结果:")
    print("-" * 60)
    if result:
        print_color(result, "green")
    else:
        print_color("解密失败!", "red")
    print("-" * 60)

    if not result:
        print_color("\n解密失败可能的原因:", "yellow")
        print("1. 输入的加密API密钥不正确")
        print("2. 解密密码不正确")
        print("3. 输入的不是有效的V2格式加密API密钥")
        print("4. 不支持V1格式密钥，V2.1.5版本的密钥不再兼容")

    input("\n按回车返回主菜单...")


def main() -> None:
    """主函数"""
    try:
        while True:
            choice = show_menu()

            if choice == "1":
                encrypt_api_key_menu()
            elif choice == "2":
                decrypt_api_key_menu()
            elif choice == "3":
                set_provider_api_key()
            elif choice == "4":
                clear_screen()
                print_color("感谢使用，再见!", "green")
                break
            else:
                print_color("\n无效选项，请重新输入!", "red")
                input("按回车继续...")
    except KeyboardInterrupt:
        # 处理Ctrl+C
        clear_screen()
        print_color("\n程序已被用户中断，再见!", "yellow")
    except Exception as e:
        # 处理其他异常
        clear_screen()
        print_color(f"\n发生错误: {e}", "red")
        print("请确保已正确安装所需库: pip install cryptography")
        input("\n按回车退出...")


if __name__ == "__main__":
    main()
