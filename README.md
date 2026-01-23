# WeibanPro 微伴助手

基于 Python 和 PyQt5 开发的微伴网课平台智能辅助工具，支持全自动刷课、智能题库答题、验证码自动识别等功能。

## 📢 最新更新 (2026-01-23)

### 🎉 重大版本更新 v2.0.0

本次更新对项目进行了全面重构和优化，整合了程序，打造了一个更强大、更稳定的微伴助手。

**主要更新内容：**
- ✨ **新增考试重考系统** - 支持 GUI 交互式重考确认，智能检测分数并提示重考
- 📊 **优化答题显示** - 采用简洁清晰的显示风格，每道题显示完整的题目和答案信息
- 📚 **本地题库优先策略** - 优先使用本地题库，考试后自动同步正确答案
- 🔧 **代码架构优化** - 整合核心功能，优化代码结构，提高可维护性

**详细更新日志请查看 [CHANGELOG.md](CHANGELOG.md)**

---

## 注意事项

仅供学习参考，不能用于非法用途，请在下载后 24 小时内删除。使用本工具产生的任何后果由使用者自行承担。

## 使用方法

### 前提条件

1. Python 3.8+（推荐 3.11-3.12 版本）
2. 安装时勾选 "Add Python to PATH" 选项
3. 良好的网络环境

### 安装依赖

#### 方法一：直接安装（简单）

1. 进入项目文件夹
2. Shift+右键，选择 "PowerShell 打开" 或 "终端打开"
3. 执行以下命令（一行一行输入并回车）：

```shell
# 设置国内镜像源（可选，加速安装）
pip config set global.index-url https://mirrors.aliyun.com/pypi/simple
pip config set install.trusted-host mirrors.aliyun.com

# 安装依赖
pip install -r requirements.txt
```

#### 方法二：使用虚拟环境（推荐，避免依赖冲突）

```shell
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境（Windows PowerShell）
venv\Scripts\Activate.ps1

# 激活虚拟环境（Windows 命令提示符）
venv\Scripts\activate.bat

# 安装依赖
pip install -r requirements.txt

# 退出虚拟环境
deactivate
```

### 运行工具

在命令窗口输入以下命令并回车：

```shell
python main.py
```

### 使用步骤

1. **登录设置**
   - 在左侧面板输入微伴账号、密码和完整的学校中文名称
   - 点击 "登录获取课程" 按钮

2. **任务配置**
   - 从下拉菜单选择要学习的课程
   - 设置考试时长（建议 240-300 秒）
   - 设置允许错题数量（建议 3-5 题）

3. **开始运行**
   - 点击 "开始任务" 按钮
   - 程序将自动完成学习任务，右侧可查看实时进度

### 注意事项

- 运行时请不要关闭程序窗口，否则任务会终止
- 考试时会有等待时间，请耐心等待
- AI 功能需要额外配置（见 `ai.conf` 文件或程序内 AI 配置）

## 核心功能

### 🚀 自动登录系统
- ✅ 支持账号密码登录
- ✅ 集成 ddddocr 验证码自动识别
- ✅ 支持手动验证码输入
- ✅ 自动处理登录流程和会话管理

### 📚 智能刷课系统
- ✅ 支持多种课程类型：推送课、自选课、必修课
- ✅ 支持特殊课程：安全实训、开放课程、Moon课程等
- ✅ 模拟真人学习行为，随机学习时长（15-20秒/课程）
- ✅ 智能跳过需要验证码的课程
- ✅ 实时进度反馈和详细日志记录

### 🤖 智能答题系统
- ✅ 内置海量本地题库（QuestionBank/result.json）
- ✅ 模糊匹配算法，提高题库利用率
- ✅ AI 辅助答题（支持 OpenAI、DeepSeek、智谱 AI 等）
- ✅ 自动提交答案，支持考试时长设置
- ✅ 错题阈值控制，模拟真实答题准确率
- ✅ 考试后自动同步正确答案到本地题库
- ✅ **新增：考试重考功能** - 支持 GUI 交互式重考确认

### 🎨 现代化 UI 界面
- ✅ 卡片式布局，清晰的信息层级
- ✅ 动态交互效果，果冻按钮动画
- ✅ 实时监控和进度显示
- ✅ 无边框弹窗设计
- ✅ 美观的日志展示和状态提示

## 常见问题

**Q: 登录失败怎么办？**
A: 检查账号密码是否正确，确保学校名称输入完整（不要用简称）。如果验证码识别失败，尝试手动输入验证码。

**Q: 题库里没有我的题？**
A: 程序会自动尝试使用 AI 或随机策略答题，并收集新题目到本地题库。您也可以手动更新题库文件。

**Q: 验证码识别失败率高？**
A: 验证码识别受多种因素影响，您可以：
- 取消勾选 "自动识别验证码"，手动输入验证码
- 更新 ddddocr 版本：`pip install --upgrade ddddocr`

**Q: 程序运行报错？**
A: 尝试以下解决方案：
- 确保 Python 版本为 3.8+ 
- 尝试重新安装依赖：`pip install -r requirements.txt --force-reinstall`
- 检查网络连接是否正常
- 以管理员身份运行命令行

**Q: 运行时出现 "ModuleNotFoundError"？**
A: 这表示缺少某个依赖包，执行以下命令安装：`pip install 缺少的包名`

**Q: 为什么考试提交失败？**
A: 可能是因为：
- 考试时间设置过短
- 网络连接不稳定
- 错题数量超过了设置的阈值

**Q: 如何更新题库？**
A: 题库会自动收集新题目，您也可以手动替换 `QuestionBank/result.json` 文件。

**Q: 程序可以最小化运行吗？**
A: 可以将程序最小化到后台运行，但不要关闭窗口，否则任务会终止。

## AI 配置（可选）

1. 运行程序，点击 "AI 配置" 按钮
2. 填写 AI 服务提供商的 API 地址、API 密钥和模型名称
3. 支持 OpenAI、DeepSeek、智谱 AI 等 OpenAI 兼容接口

## 项目结构

```text
WeibanPro/
├── main.py              # [核心] 主程序入口，PyQt5 GUI 实现
├── WBCore.py            # [核心] 业务逻辑库，包含登录、刷课、答题等功能
├── QuestionBank/        # [数据] 题库系统
│   ├── __init__.py      # 题库模块初始化
│   ├── QuestionBank.py  # 题库管理功能
│   └── result.json      # 海量题库数据
├── assets/              # 资源文件
│   └── API-LIST.txt     # API 接口列表
├── encrypted.py         # 加密算法辅助模块
├── encrypted.js         # JavaScript 加密实现
├── crypto-js.min.js     # CryptoJS 库
├── ai.conf              # AI 配置文件模板
├── requirements.txt     # 项目依赖清单
├── icon.ico             # 程序图标
├── .github/             # GitHub 配置
│   └── workflows/       # GitHub Actions 工作流
│       └── build.yml    # 自动构建配置
├── .gitignore           # Git 忽略文件配置
├── LICENSE              # 许可证文件
└── CHANGELOG.md         # 更新日志
```

## 贡献指南

欢迎大家参与项目贡献！如果您想为 WeibanPro 做出贡献，可以：

1. **报告问题**：在 GitHub Issues 中提交 bug 报告或功能建议
2. **提交代码**：
   - Fork 项目仓库
   - 创建新分支：`git checkout -b feature/your-feature-name`
   - 提交更改：`git commit -m "Add your feature description"`
   - 推送分支：`git push origin feature/your-feature-name`
   - 创建 Pull Request
3. **完善文档**：改进 README.md 或添加新的文档
4. **更新题库**：分享您的题库数据

## 许可证

本项目采用 MIT 许可证开源，详细信息请查看 [LICENSE](LICENSE) 文件。

## 致谢

感谢所有为本项目做出贡献的开发者和用户！特别感谢：

- [ddddocr](https://github.com/sml2h3/ddddocr) - 验证码识别库
- 所有提供题库数据的用户
- 所有报告问题和提供建议的用户


---

如果觉得好用，请给个 Star ⭐️ 支持一下！
