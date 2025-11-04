"""
网络工具模块
提供网络连接检查、API健康检测等功能
"""

import socket
import logging
import ssl
from typing import Dict, Optional, Any, TypedDict
import time
import http.client

# 统一路径管理：移除对 sys.path 的注入与手工路径拼接
# 使用包内绝对导入，保持与打包环境一致
# 导入配置常量
from .constants import NetworkConstants

logger = logging.getLogger(__name__)


def create_ssl_context(config: Optional[Any] = None) -> ssl.SSLContext:
    """
    创建一个自定义的SSL上下文，以提高网络兼容性。

    Args:
        config: 配置对象，用于读取SSL设置

    Returns:
        ssl.SSLContext: 配置好的SSL上下文对象。
    """
    # 彻底重构：避免在打包环境中使用不稳定的 ssl.create_default_context()
    # 手动创建 SSLContext 并加载默认证书
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs()

    tcp_config = getattr(config, "tcp_connector", {}) if config else {}

    # 检查SSL验证配置，如果禁用则设置相应的标志
    ssl_verify = tcp_config.get("ssl_verify", True)
    ssl_check_hostname = tcp_config.get("ssl_check_hostname", True)

    if not ssl_verify:
        logger.info("[SSL配置] SSL证书验证已根据配置文件设置为禁用状态")
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        logger.info(
            "[SSL上下文] SSL证书验证已禁用。check_hostname=False, verify_mode=CERT_NONE"
        )
    else:
        # 从配置中读取最低TLS版本，扩展四级fallback
        min_tls_version_str = tcp_config.get("min_tls_version", "TLSv1_2")

        # 四级fallback机制：
        # 1. 用户指定的TLS版本
        # 2. default_TLS_version（最新可用）
        # 3. TLSv1_2（最常见的兼容版本）
        # 4. 最慢可用TLS版本（最后绝对fallback）
        fallback_versions = [
            min_tls_version_str,
            "default_TLS_version",
            "TLSv1_2",
            None,
        ]

        min_tls_version = None
        for version_str in fallback_versions:
            if version_str == "default_TLS_version":
                # 使用Python默认TLS版本
                try:
                    min_tls_version = ssl.TLSVersion.TLSv1_2  # 默认安全版本
                    break
                except AttributeError:
                    continue
            elif version_str is None:
                # 获取最慢可用TLS版本作为最后fallback
                try:
                    # 尝试获取最低版本（按优先级排序）
                    for possible_version in [
                        "TLSv1_0",
                        "TLSv1_1",
                        "TLSv1_2",
                        "TLSv1_3",
                    ]:
                        try:
                            min_tls_version = getattr(ssl.TLSVersion, possible_version)
                            break
                        except AttributeError:
                            continue
                    if min_tls_version is None:
                        # 如果都没有，使用系统最小版本
                        min_tls_version = context.minimum_version
                except Exception:
                    logger.error("[SSL上下文] 获取TLS版本失败，使用系统默认")
                    min_tls_version = context.minimum_version
                break
            else:
                # 尝试用户指定或标准版本
                try:
                    min_tls_version = getattr(ssl.TLSVersion, version_str)
                    break
                except AttributeError:
                    logger.debug(
                        f"[SSL上下文] TLS版本 {version_str} 不可用，继续fallback"
                    )
                    continue

        # 应用配置
        if min_tls_version is not None:
            context.minimum_version = min_tls_version
            logger.info(
                f"[SSL上下文] 最低TLS版本设置为: {min_tls_version.name}，经过四级fallback"
            )
        else:
            logger.warning("[SSL上下文] 无法设置TLS版本，使用系统默认")

        # 从配置中读取密码套件
        ciphers = tcp_config.get("ciphers")
        if ciphers:
            try:
                context.set_ciphers(ciphers)
                logger.info(f"[SSL上下文] 已设置自定义密码套件: {ciphers}")
            except ssl.SSLError as e:
                logger.warning(
                    f"[SSL上下文] 无法设置自定义密码套件，将使用系统默认值: {e}"
                )
        else:
            logger.info("[SSL上下文] 未设置自定义密码套件，使用系统默认值。")

        # 设置主机名验证
        context.check_hostname = ssl_check_hostname
        logger.info(f"[SSL上下文] 主机名检查设置为: {ssl_check_hostname}")

    logger.debug(
        f"[SSL上下文] 最终SSL上下文配置: check_hostname={context.check_hostname}, verify_mode={context.verify_mode.name}, minimum_version={context.minimum_version.name}"
    )
    return context


class NetworkStatusSummary(TypedDict):
    connected: bool
    hosts_status: Dict[str, bool]
    check_time: float
    diagnostics: Dict[str, Any]


class NetworkChecker:
    """网络连接检查器 - 优化版"""

    def __init__(self, config: Optional[Any] = None):
        """初始化网络检查器

        Args:
            config: 配置对象
        """
        self.config = config
        self._last_check_time = 0.0
        self._last_check_result = False
        # 检查间隔（秒），可在 config.network_check.interval 中覆盖，默认 5s
        default_interval = 5
        if (
            config
            and hasattr(config, "network_check")
            and isinstance(config.network_check, dict)
        ):
            default_interval = config.network_check.get("interval", default_interval)
        self._check_interval = max(1, default_interval)

    def is_network_connected(self, force_check: bool = False) -> bool:
        """检查网络连接状态，优化超时设置

        Args:
            force_check: 是否强制检查（忽略缓存）

        Returns:
            bool: 网络是否连接
        """
        logger.debug(f"检查网络连接，强制检查: {force_check}")
        current_time = time.time()

        # 如果不是强制检查且距离上次检查时间较短，返回缓存结果
        if (
            not force_check
            and (current_time - self._last_check_time) < self._check_interval
        ):
            logger.debug(f"使用网络连接缓存结果: {self._last_check_result}")
            return self._last_check_result

        # 获取网络检查配置
        network_config = (
            getattr(self.config, "network_check", {}) if self.config else {}
        )
        hosts = network_config.get(
            "hosts", NetworkConstants.NETWORK_CHECK_HOSTS_DEFAULT
        )
        port = network_config.get("port", NetworkConstants.NETWORK_CHECK_PORT_DEFAULT)
        # 优化超时设置，使其更加灵活
        timeout = network_config.get(
            "timeout", NetworkConstants.NETWORK_CHECK_TIMEOUT_DEFAULT
        )
        # 新增：获取HTTPS检测的超时设置，默认为TCP超时的1.5倍，但不超过5秒
        https_timeout = network_config.get("https_timeout", min(5.0, timeout * 1.5))

        logger.debug(
            f"网络检查配置: hosts={hosts}, port={port}, tcp_timeout={timeout}, https_timeout={https_timeout}"
        )

        tcp_ok = False
        for host in hosts:
            logger.debug(f"尝试连接到主机(TCP): {host}:{port}")
            if self._check_host_connection(host, port, timeout):
                logger.info(f"网络连接成功 (TCP)，主机: {host}")
                tcp_ok = True
                break
            else:
                logger.debug(f"TCP 连接失败: {host}:{port}")

        # 如果 TCP 成功，直接返回 True
        if tcp_ok:
            self._last_check_result = True
            self._last_check_time = current_time
            return True

        # ---------------- HTTPS 备用检测 ----------------
        logger.debug("TCP 检测全部失败，尝试 HTTPS 检测 …")
        for host in hosts:
            try:
                conn = http.client.HTTPSConnection(
                    host,
                    443,
                    timeout=https_timeout,
                    context=create_ssl_context(self.config),
                )
                conn.request("HEAD", "/")
                resp = conn.getresponse()
                conn.close()
                if resp.status < 500:
                    logger.info(f"网络连接成功 (HTTPS)，主机: {host}")
                    self._last_check_result = True
                    self._last_check_time = current_time
                    return True
            except Exception as https_err:
                logger.debug(f"HTTPS 检测失败 {host}: {https_err}")

        logger.warning("所有网络检查主机 (TCP & HTTPS) 均失败")
        self._last_check_result = False
        self._last_check_time = current_time
        return False

    def _check_host_connection(self, host: str, port: int, timeout: float) -> bool:
        """检查到特定主机的连接

        Args:
            host: 主机地址
            port: 端口号
            timeout: 超时时间

        Returns:
            bool: 连接是否成功
        """
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.error, OSError):
            return False

    def get_network_status(self) -> NetworkStatusSummary:
        """获取详细的网络状态信息，增加诊断信息

        Returns:
            Dict[str, Any]: 网络状态信息
        """
        network_config = (
            getattr(self.config, "network_check", {}) if self.config else {}
        )
        hosts = network_config.get(
            "hosts", NetworkConstants.NETWORK_CHECK_HOSTS_DEFAULT
        )
        port = network_config.get("port", NetworkConstants.NETWORK_CHECK_PORT_DEFAULT)
        timeout = network_config.get(
            "timeout", NetworkConstants.NETWORK_CHECK_TIMEOUT_DEFAULT
        )
        # 新增：获取HTTPS检测的超时设置
        https_timeout = network_config.get("https_timeout", min(5.0, timeout * 1.5))

        status: NetworkStatusSummary = {
            "connected": False,
            "hosts_status": {},
            "check_time": time.time(),
            "diagnostics": {},
        }

        for host in hosts:
            host_connected = self._check_host_connection(host, port, timeout)
            status["hosts_status"][host] = host_connected
            if host_connected:
                status["connected"] = True

        # 添加诊断信息
        status["diagnostics"] = {
            "hosts": hosts,
            "port": port,
            "tcp_timeout": timeout,
            "https_timeout": https_timeout,
            "check_interval": self._check_interval,
        }

        return status
