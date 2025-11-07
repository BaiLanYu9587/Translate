# GitHub Actions 自动打包说明

## 工作流程

本项目配置了 GitHub Actions 自动打包工作流，可以在以下情况自动触发构建：

### 触发条件

1. **推送到 main 分支** - 每次推送代码到 main 分支时自动构建
2. **创建版本标签** - 创建 `v*` 格式的标签时自动构建并发布 Release
3. **Pull Request** - 创建或更新 PR 时进行构建测试
4. **手动触发** - 在 GitHub Actions 页面手动运行

### 构建产物

每次构建会生成两个可执行文件：
- `MultiLangTranslator-v{VERSION}.exe` - 主程序
- `APIKeyTool-v{VERSION}.exe` - API密钥加密工具

### 如何下载构建产物

#### 方式1：从 Actions 页面下载

1. 访问项目的 Actions 页面
2. 点击最新的构建任务
3. 在页面底部的 "Artifacts" 区域下载 `MultiLangTranslator-v{VERSION}-windows.zip`

#### 方式2：从 Release 页面下载（仅限标签构建）

1. 访问项目的 Releases 页面
2. 下载对应版本的 `.exe` 文件

### 如何创建 Release

要创建一个正式的 Release 版本：

```bash
# 1. 确保所有更改已提交
git add .
git commit -m "Release v2.2.5"

# 2. 创建并推送标签
git tag v2.2.5
git push origin v2.2.5

# 3. GitHub Actions 会自动构建并创建 Release
```

### 本地测试构建

在推送到 GitHub 之前，可以在本地测试构建：

```bash
# 运行构建脚本
python build.py

# 检查 dist 目录下的生成文件
ls dist/
```

### 工作流配置文件

- `.github/workflows/build-release.yml` - 主构建工作流

### 依赖项

工作流会自动安装以下依赖：
- Python 3.11
- PyInstaller
- 项目所需的所有 Python 包

### 注意事项

1. **构建时间**: 完整构建大约需要 5-10 分钟
2. **构建环境**: 使用 Windows 最新版本的 GitHub Runner
3. **文件大小**: 生成的 exe 文件约 40-80 MB
4. **保留时间**: Artifacts 默认保留 30 天

### 故障排查

如果构建失败：

1. 检查 Actions 页面的构建日志
2. 确认所有依赖在 requirements.txt 或 pyproject.toml 中正确列出
3. 确认 core/constants.py 中的 APP_VERSION 可以正确读取
4. 本地运行 `python build.py` 测试

### 手动触发构建

1. 访问项目的 Actions 页面
2. 选择 "Build and Release" 工作流
3. 点击 "Run workflow" 按钮
4. 选择分支并点击 "Run workflow"
