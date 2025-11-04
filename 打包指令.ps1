# 脚本运行指令.\打包指令.ps1


# 切换到项目目录
# Set-Location "XXX"

# 切换到脚本所在目录（项目根目录）
Set-Location (Split-Path -Parent $PSCommandPath)

# 创建/定位打包输出目录
$DistPath = Join-Path (Get-Location) "编译"
if (-not (Test-Path $DistPath)) {
    New-Item -ItemType Directory -Path $DistPath | Out-Null
}

# 统一版本号：从 core/constants.py 读取 APP_VERSION
# 依赖 Poetry 虚拟环境运行 Python，一处维护版本即可
$APP_VERSION = (
    poetry run python -c "from core.constants import APP_VERSION; print(APP_VERSION)" 2>$null
).Trim()
if (-not $APP_VERSION) {
    Write-Error "无法读取 APP_VERSION，请检查 core/constants.py 或 Poetry 环境"
    exit 1
}

$AppName = "多语言互译器v$APP_VERSION"
$ApiToolName = "API加解密工具v$APP_VERSION"

# 执行 PyInstaller 打包命令（通过 Poetry 环境）
poetry run pyinstaller --clean --noconfirm --onefile `
  --add-data "core/*;core/" `
  --add-data "utils/*;utils/" `
  --add-data "图标.ico;." `
  --add-data "openssl_dll/*;openssl_dll/" `
  --hidden-import "pyautogui" `
  --hidden-import "yaml" `
  --hidden-import "keyboard" `
  --hidden-import "pycld2" `
  --hidden-import "cryptography" `
  --hidden-import "PyQt6" `
  --hidden-import "aiohttp" `
  --hidden-import "pynput" `
  --hidden-import "regex" `
  --hidden-import "ruamel.yaml" `
  --hidden-import "sqlite3" `
  --hidden-import "_sqlite3" `
  --hidden-import "logging.handlers" `
  --hidden-import "socket" `
  --hidden-import "ssl" `
  --hidden-import "json" `
  --hidden-import "collections" `
  --hidden-import "asyncio" `
  --hidden-import "threading" `
  --hidden-import "importlib.util" `
  --hidden-import "time" `
  --hidden-import "os" `
  --hidden-import "sys" `
  --hidden-import "io" `
  --hidden-import "queue" `
  --hidden-import "signal" `
  --hidden-import "atexit" `
  --hidden-import "dataclasses" `
  --hidden-import "typing" `
  --hidden-import "re" `
  --hidden-import "hashlib" `
  --hidden-import "base64" `
  --hidden-import "urllib" `
  --hidden-import "urllib.parse" `
  --hidden-import "http" `
  --hidden-import "http.client" `
  --hidden-import "utils.api_crypto" `
  --hidden-import "pyperclip" `
  --hidden-import "win32gui" `
  --hidden-import "win32api" `
  --hidden-import "PIL" `
  --hidden-import "pygetwindow" `
  --hidden-import "certifi" `
  --collect-submodules "sqlite3" `
  --collect-submodules "logging" `
  --collect-submodules "urllib" `
  --collect-submodules "http" `
  --collect-submodules "PIL" `
  --collect-submodules "pywin32" `
  --icon "图标.ico" `
  --name "$AppName" `
  --console `
  --distpath $DistPath `
  "start.py"

# API 加解密工具的打包命令（通过 Poetry 环境）
poetry run pyinstaller --clean --noconfirm --onefile `
  --add-data "utils/api_crypto.py;utils/" `
  --add-data "openssl_dll/*;openssl_dll/" `
  --hidden-import "yaml" `
  --icon "图标.ico" `
  --name "$ApiToolName" `
  --console `
  --distpath $DistPath `
  "utils/api_key_tool.py"
