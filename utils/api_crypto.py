import base64
import secrets
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

# 配置日志
logger = logging.getLogger(__name__)


class SecureString:
    """安全字符串类，用于在内存中安全存储敏感数据"""

    def __init__(self, data: str):
        self._data = bytearray(data.encode("utf-8"))
        self._hash = hashlib.sha256(self._data).hexdigest()[:8]

    def get(self) -> str:
        """获取字符串内容"""
        return self._data.decode("utf-8")

    def clear(self) -> None:
        """清除内存中的敏感数据"""
        if hasattr(self, "_data"):
            try:
                # 原地覆盖，避免重新分配
                for i in range(len(self._data)):
                    self._data[i] = 0
                # 追加两轮随机覆盖，降低内存残留概率
                for i in range(len(self._data)):
                    self._data[i] = secrets.randbits(8)
                for i in range(len(self._data)):
                    self._data[i] = 0
            finally:
                # 最后删除引用
                del self._data
                if hasattr(self, "_hash"):
                    del self._hash

    def __del__(self) -> None:
        """析构时自动清除"""
        self.clear()

    def __str__(self) -> str:
        return f"SecureString(hash={self._hash})"

    def __repr__(self) -> str:
        return self.__str__()


class ApiCrypto:
    """API密钥加密解密工具类，使用AES-GCM模式"""

    def __init__(self, password: str | None = None) -> None:
        """初始化加密工具

        Args:
            password: 加密密码，默认为None时使用默认密码
        """
        self._password = SecureString(password or "www.google.com")
        # 固定的盐值，只支持v2版本
        self._salt = b"api_translator_salt_v2"
        # 派生一个256位的密钥
        self._key: bytes | bytearray = self._derive_key(
            self._password.get().encode(), self._salt
        )
        # 验证密钥强度
        self._validate_key_strength()

    def _derive_key(self, password: bytes, salt: bytes) -> bytes:
        """派生加密密钥

        Args:
            password: 密码
            salt: 盐值

        Returns:
            bytes: 派生的密钥
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256位密钥
            salt=salt,
            iterations=100000,
        )
        return kdf.derive(password)

    def _validate_key_strength(self) -> None:
        """验证密钥强度"""
        try:
            # 检查密钥长度
            if len(self._key) != 32:
                logger.warning("密钥长度不是256位")

            # 检查密钥熵（简单检查）
            unique_bytes = len(set(self._key))
            if unique_bytes < 16:  # 至少应该有16个不同的字节值
                logger.warning("密钥熵可能不足")

            logger.debug("密钥强度验证完成")

        except Exception as e:
            logger.error(f"密钥强度验证失败: {e}")

    def _secure_random_nonce(self) -> bytes:
        """生成安全的随机数"""
        return secrets.token_bytes(12)  # 使用密码学安全的随机数生成器

    def _validate_api_key_format(self, api_key: str) -> bool:
        """验证API密钥格式的合理性"""
        if not api_key:
            return False

        # 基本长度检查
        if len(api_key) < 10:
            logger.warning("API密钥长度过短")
            return False

        if len(api_key) > 500:
            logger.warning("API密钥长度过长")
            return False

        # 检查是否包含明显的敏感信息泄露
        suspicious_patterns = ["password", "secret", "private", "key=", "token="]
        api_key_lower = api_key.lower()
        for pattern in suspicious_patterns:
            if pattern in api_key_lower:
                logger.warning(f"API密钥包含可疑模式: {pattern}")

        return True

    def encrypt(self, api_key: str) -> str:
        """加密API密钥

        Args:
            api_key: 原始API密钥

        Returns:
            str: Base64编码的加密API密钥
        """
        if not api_key:
            return ""

        # 验证API密钥格式
        if not self._validate_api_key_format(api_key):
            logger.warning("API密钥格式验证失败，但继续加密")

        # 避免中间创建多份不可变 bytes/str，使用一次性缓冲转换
        api_key_ba = None
        try:
            # 使用安全的随机数生成器
            nonce = self._secure_random_nonce()

            # 创建AES-GCM加密器
            aesgcm = AESGCM(self._key)

            # 使用 bytearray 作为中间缓冲，减少不可控副本
            api_key_ba = bytearray(api_key.encode("utf-8"))

            # 加密API密钥
            ciphertext = aesgcm.encrypt(nonce, bytes(api_key_ba), None)

            # 添加版本标识和校验和
            version = b"\x02"  # 版本2
            checksum = hashlib.sha256(nonce + ciphertext).digest()[:4]  # 4字节校验和

            # 将版本、随机数、密文和校验和拼接后进行Base64编码
            encrypted_data = version + nonce + ciphertext + checksum
            encrypted = base64.b64encode(encrypted_data).decode("utf-8")

            logger.debug(f"API密钥已加密，长度: {len(encrypted)}, 版本: 2")
            return encrypted

        except Exception as e:
            logger.error(f"加密API密钥失败: {type(e).__name__}: {e}")
            return ""
        finally:
            # 擦除本地缓冲
            try:
                if api_key_ba is not None:
                    for i in range(len(api_key_ba)):
                        api_key_ba[i] = 0
            finally:
                api_key_ba = None

    def decrypt(self, encrypted_api_key: str) -> str:
        """解密API密钥，只支持V2格式

        Args:
            encrypted_api_key: Base64编码的加密API密钥

        Returns:
            str: 原始API密钥，如果格式无效或非V2格式则返回空字符串
        """
        if not encrypted_api_key:
            return ""

        plaintext_ba = None
        try:
            # 解码Base64
            data = base64.b64decode(encrypted_api_key)

            if len(data) < 17:  # 最小长度：版本(1) + nonce(12) + checksum(4)
                logger.error("加密数据长度不足或格式不是V2版本")
                return ""

            # 检查是否为版本2格式（有版本字节）
            if data[0:1] == b"\x02":
                # 版本2格式：版本(1) + nonce(12) + ciphertext(变长) + checksum(4)
                logger.debug("检测到V2格式")

                nonce = data[1:13]
                ciphertext = data[13:-4]
                checksum = data[-4:]

                # 验证校验和
                expected_checksum = hashlib.sha256(nonce + ciphertext).digest()[:4]
                if checksum != expected_checksum:
                    logger.error("校验和验证失败")
                    return ""

                # 使用v2密钥解密
                aesgcm = AESGCM(self._key)
                plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                # 使用可变缓冲区接收解密数据，便于擦除
                plaintext_ba = bytearray(plaintext)
                api_key = bytes(plaintext_ba).decode("utf-8")
                logger.debug("V2格式解密成功")
                return api_key
            else:
                # 不支持的格式
                logger.error("不支持的API密钥格式，只接受V2格式")
                return ""

        except Exception as e:
            logger.error(f"解密API密钥失败: {type(e).__name__}: {e}")
            return ""
        finally:
            # 擦除本地明文缓冲
            try:
                if plaintext_ba is not None:
                    for i in range(len(plaintext_ba)):
                        plaintext_ba[i] = 0
            finally:
                plaintext_ba = None

    def is_encrypted(self, api_key: str) -> bool:
        """检查API密钥是否为有效的V2加密格式，但不实际解密。

        此方法通过验证Base64编码、版本标识和校验和来判断，避免了
        不必要的解密开销和重复日志。

        Args:
            api_key: 待检查的API密钥字符串。

        Returns:
            bool: 如果是有效的V2加密格式，则返回True，否则返回False。
        """
        if not api_key or not isinstance(api_key, str):
            return False

        try:
            # 1. 尝试Base64解码
            data = base64.b64decode(api_key)

            # 2. 检查最小长度和版本标识
            # V2格式: 版本(1) + Nonce(12) + 密文(至少1) + 校验和(4) = 至少18字节
            if len(data) < 18 or data[0:1] != b"\x02":
                return False

            # 3. 提取组件
            nonce = data[1:13]
            ciphertext = data[13:-4]
            checksum = data[-4:]

            # 4. 验证校验和
            expected_checksum = hashlib.sha256(nonce + ciphertext).digest()[:4]
            if checksum != expected_checksum:
                # 校验和不匹配，不是有效的加密数据
                return False

            # 所有检查通过，是有效的V2格式
            return True

        except (ValueError, TypeError):
            # Base64解码失败或类型错误，肯定不是加密格式
            return False

    def clear_sensitive_data(self) -> None:
        """清理内存中的敏感数据"""
        try:
            if hasattr(self, "_password"):
                self._password.clear()

            if hasattr(self, "_key"):
                # 确保为可变缓冲区，避免在循环内反复创建新对象
                if not isinstance(self._key, bytearray):
                    try:
                        # 将只读 bytes 转换为 bytearray 一次性完成
                        ba = bytearray(self._key)
                    except Exception:
                        # 无法转换时，尽力而为：以新缓冲区覆盖引用
                        ba = bytearray(self._key[:])
                    self._key = ba
                # 三段式擦写：0x00 -> 随机 -> 0x00
                for i in range(len(self._key)):
                    self._key[i] = 0
                for i in range(len(self._key)):
                    self._key[i] = secrets.randbits(8)
                for i in range(len(self._key)):
                    self._key[i] = 0
                del self._key

            logger.debug("敏感数据已清理")

        except Exception as e:
            logger.error(f"清理敏感数据失败: {e}")

    def __del__(self) -> None:
        """析构时自动清理敏感数据"""
        self.clear_sensitive_data()


# 创建命令行加解密工具函数
def encrypt_api_key(api_key: str, password: str | None = None) -> str:
    """加密API密钥的命令行工具函数

    Args:
        api_key: 要加密的API密钥
        password: 加密密码，默认为None

    Returns:
        str: 加密后的API密钥
    """
    crypto = ApiCrypto(password)
    encrypted = crypto.encrypt(api_key)
    return encrypted


def decrypt_api_key(encrypted_api_key: str, password: str | None = None) -> str:
    """解密API密钥的命令行工具函数

    Args:
        encrypted_api_key: 要解密的API密钥
        password: 解密密码，默认为None

    Returns:
        str: 解密后的API密钥
    """
    crypto = ApiCrypto(password)
    decrypted = crypto.decrypt(encrypted_api_key)
    return decrypted


# 命令行工具入口
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="API密钥加密解密工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-e", "--encrypt", help="要加密的API密钥")
    group.add_argument("-d", "--decrypt", help="要解密的API密钥")
    parser.add_argument("-p", "--password", help="加密/解密密码，不提供则使用默认密码")

    args = parser.parse_args()

    if args.encrypt:
        result = encrypt_api_key(args.encrypt, args.password)
        print(f"加密结果: {result}")
    elif args.decrypt:
        result = decrypt_api_key(args.decrypt, args.password)
        print(f"解密结果: {result}")
