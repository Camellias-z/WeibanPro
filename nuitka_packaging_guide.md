# Nuitka打包指南：WeibanPro项目

## 项目分析

### 项目结构
- **主入口文件**: `mian.py` (注意文件名是`mian.py`不是`main.py`)
- **核心模块**: `WBCore.py`
- **辅助文件**: `encrypted.py`, `encrypted.js`, `crypto-js.min.js`
- **资源文件**: `icon.ico`, `ai.conf`
- **数据目录**: `QuestionBank/`
- **依赖库**: 见`requirements.txt`

### 关键依赖
- PyQt5 (GUI框架)
- requests (网络请求)
- ddddocr (验证码识别)
- openai (AI功能)
- onnxruntime==1.20.1 (AI模型推理)
- Pillow (图像处理)

## Nuitka GUI工具打包步骤

### 1. 基本配置 (文件路径配置)

| 配置项 | 设置值 | 操作说明 |
|-------|--------|---------|
| Python解释器 | 选择你使用的Python解释器路径 | 点击"浏览"选择，通常位于`C:\Python3x\python.exe`或虚拟环境中的`venv\Scripts\python.exe` |
| 主文件 | 选择项目主文件 | 浏览选择`E:\Tools\amusing\code\test\WeibanPro\mian.py` |
| 图标文件 | 选择程序图标 | 浏览选择`E:\Tools\amusing\code\test\WeibanPro\icon.ico` |
| 输出目录 | 设置打包输出路径 | 建议选择一个新目录，如`E:\Tools\amusing\code\test\WeibanPro\output` |

### 2. 常用选项配置

| 选项 | 设置值 | 说明 |
|-----|--------|------|
| 输出目录 | 与文件路径配置中的输出目录保持一致 | 确保输出位置统一 |
| 可执行文件名称 | `WeibanPro` | 生成的exe文件名称 |
| 控制台窗口 | 建议勾选"不显示控制台窗口" | 因为是GUI程序，不需要控制台 |
| 启用UPX压缩 | 勾选 | 进一步减小打包体积（需提前安装UPX） |

### 3. 插件选项配置

| 插件 | 状态 | 说明 |
|-----|------|------|
| PyQt5 | 勾选 | 必须启用，项目使用PyQt5 GUI框架 |
| ddddocr | 勾选 | 验证码识别库，需要特殊处理 |
| requests | 勾选 | 网络请求库 |
| openai | 勾选 | AI功能依赖 |
| onnxruntime | 勾选 | AI模型推理依赖 |

### 4. Python标志配置

| 选项 | 状态 | 说明 |
|-----|------|------|
| 优化级别 | 选择`-O2` | 最高优化级别，减小体积并提高性能 |
| 包含调试符号 | 取消勾选 | 发布版本不需要调试符号 |
| 移除断言 | 勾选 | 进一步减小体积 |

### 5. 高级选项配置

| 选项 | 状态 | 说明 |
|-----|------|------|
| 包含数据文件 | 添加以下条目 | 确保资源文件被正确打包 |
| | `icon.ico` -> `.` | 主程序图标 |
| | `ai.conf` -> `.` | AI配置文件 |
| | `QuestionBank/` -> `QuestionBank/` | 题库目录 |
| | `encrypted.js` -> `.` | 加密相关JS文件 |
| | `crypto-js.min.js` -> `.` | 加密库JS文件 |
| 包含Python模块 | 添加以下模块 | 确保所有依赖模块被正确包含 |
| | `WBCore` | 核心功能模块 |
| | `encrypted` | 加密功能模块 |
| | `ddddocr` | 验证码识别 |
| | `openai` | AI功能 |
| | `onnxruntime` | AI模型推理 |
| | `PIL` | 图像处理 |
| | `requests` | 网络请求 |
| | `configparser` | 配置文件处理 |

### 6. 单文件选项配置

| 选项 | 状态 | 说明 |
|-----|------|------|
| 单文件模式 | 勾选 | 生成单个exe文件，方便分发 |
| 单文件解压目录 | 默认即可 | 或设置为`%TEMP%\WeibanPro` |
| 启用固态压缩 | 勾选 | 进一步减小单文件体积 |

### 7. 开始打包

1. 点击"开始打包"按钮
2. 等待打包完成（首次打包时间较长，后续会缓存）
3. 打包完成后，在输出目录中找到生成的`WeibanPro.exe`文件

## 命令行打包方案

如果Nuitka GUI工具使用不顺畅，可以尝试使用命令行打包。首先确保已安装Nuitka：

```bash
pip install nuitka
```

然后使用以下命令打包：

```bash
# 基础单文件打包命令
nuitka --standalone --onefile --enable-plugin=pyqt5 --enable-plugin=upx --upx-binary=upx.exe --include-data-file=icon.ico=icon.ico --include-data-file=ai.conf=ai.conf --include-data-dir=QuestionBank=QuestionBank --include-data-file=encrypted.js=encrypted.js --include-data-file=crypto-js.min.js=crypto-js.min.js --include-module=WBCore --include-module=encrypted --include-module=ddddocr --include-module=openai --include-module=onnxruntime --include-module=PIL --include-module=requests --include-module=configparser --windows-disable-console --windows-icon-from-ico=icon.ico --output-dir=output --remove-output mian.py

# 优化版本（启用更多优化）
nuitka --standalone --onefile --enable-plugin=pyqt5 --enable-plugin=upx --upx-binary=upx.exe --include-data-file=icon.ico=icon.ico --include-data-file=ai.conf=ai.conf --include-data-dir=QuestionBank=QuestionBank --include-data-file=encrypted.js=encrypted.js --include-data-file=crypto-js.min.js=crypto-js.min.js --include-module=WBCore --include-module=encrypted --include-module=ddddocr --include-module=openai --include-module=onnxruntime --include-module=PIL --include-module=requests --include-module=configparser --windows-disable-console --windows-icon-from-ico=icon.ico --output-dir=output --remove-output --optimize=2 --no-assert --enable-plugin=numpy --enable-plugin=multiprocessing mian.py
```

## 注意事项

1. **文件名注意**: 主文件是`mian.py`（不是`main.py`），打包时必须使用正确的文件名
2. **依赖处理**: ddddocr和onnxruntime是较大的依赖库，打包时间会较长
3. **资源文件**: 确保所有资源文件和目录都被正确包含，特别是`QuestionBank`目录
4. **UPX压缩**: 如需使用UPX压缩，需提前下载UPX并将其添加到系统PATH中
5. **首次运行**: 首次运行生成的exe文件时，会解压资源，可能需要几秒钟时间
6. **兼容性**: 建议在目标系统上测试打包后的程序，确保所有功能正常

## 排错指南

### 常见错误及解决方案

1. **缺少模块错误**
   - 错误信息: `ModuleNotFoundError: No module named 'xxx'`
   - 解决方案: 在命令行中添加`--include-module=xxx`或在GUI的"包含Python模块"中添加

2. **缺少资源文件错误**
   - 错误信息: 程序无法找到`QuestionBank`或其他资源文件
   - 解决方案: 确保使用`--include-data-file`或`--include-data-dir`正确包含所有资源

3. **PyQt5相关错误**
   - 错误信息: PyQt5相关组件无法加载
   - 解决方案: 确保启用了PyQt5插件，并正确包含了所有PyQt5模块

4. **onnxruntime错误**
   - 错误信息: onnxruntime相关功能无法使用
   - 解决方案: 确保使用了正确版本的onnxruntime（项目要求1.20.1），并在打包时正确包含

## 打包后测试

打包完成后，建议进行以下测试：

1. **基本功能测试**: 启动程序，检查GUI是否正常显示
2. **登录功能测试**: 尝试登录，检查验证码识别功能是否正常
3. **刷课功能测试**: 运行刷课任务，检查核心功能是否正常
4. **AI功能测试**: 测试AI答题功能（如果配置了AI）
5. **资源访问测试**: 检查程序是否能正确访问QuestionBank目录

## 性能对比

| 打包工具 | 预计打包大小 | 启动时间 | 运行性能 |
|---------|--------------|----------|----------|
| PyInstaller | ~150-200MB | 3-5秒 | 一般 |
| Nuitka | ~50-80MB | 1-2秒 | 较好 |

Nuitka打包后的程序通常比PyInstaller小30%-60%，启动更快，运行更流畅。

## 后续优化建议

1. **依赖精简**: 检查并移除不必要的依赖库
2. **代码优化**: 优化程序代码，减少不必要的导入
3. **资源压缩**: 压缩图片和其他资源文件
4. **UPX压缩**: 使用UPX进一步压缩可执行文件
5. **动态加载**: 考虑将部分大型依赖改为动态加载

希望本指南能帮助你成功使用Nuitka打包WeibanPro项目！