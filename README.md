# ⚽ 足球分析智能体

基于 **Anthropic API + Function Calling** 的 Python 足球比赛预测与分析系统。

## 技术栈

| 模块 | 技术 |
|------|------|
| AI 引擎 | Anthropic Claude API (Function Calling) |
| 预测模型 | 泊松分布 + ELO 评分系统 |
| Web 框架 | FastAPI + Jinja2 |
| 数据来源 | football-data.org API / 模拟数据降级 |

## 项目结构

```
足球大模型1.0/
├── main.py                    # 主入口 (serve/chat/predict)
├── requirements.txt           # Python 依赖
├── .env.example               # 环境变量模板
├── README.md
├── src/
│   ├── agent/
│   │   ├── football_agent.py  # 智能体核心 (Anthropic API 调度)
│   │   ├── tools.py           # 工具函数实现
│   │   └── tool_schemas.py    # Anthropic Tool Schema 定义
│   ├── models/
│   │   ├── prediction.py      # 泊松分布预测模型
│   │   └── elo.py            # ELO 评分系统
│   ├── data/
│   │   ├── api_client.py      # 足球数据 API 客户端
│   │   └── cache.py           # 缓存模块
│   ├── web/
│   │   ├── app.py             # FastAPI 应用
│   │   ├── templates/         # HTML 模板
│   │   └── static/            # 静态文件
│   └── utils/
│       └── config.py          # 配置管理
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 Anthropic API Key
```

### 3. 运行

```bash
# 启动 Web 服务
python main.py serve

# 命令行对话
python main.py chat

# 快速预测
python main.py predict Arsenal "Manchester City"
```

## 核心功能

### 🤖 AI 智能体
- 调用 Anthropic Claude API，使用 **Function Calling** 自动选择合适的工具
- 支持多轮对话，可与 AI 深入讨论比赛分析
- System Prompt 设定专业足球分析师角色

### 🔮 比赛预测
- **泊松分布模型**: 基于球队攻防实力计算期望进球和比分概率
- **ELO 评分系统**: 综合球队实力评级，提供交叉验证
- **融合预测**: 泊松(60%) + ELO(40%) 加权平均
- 输出: 胜平负概率、最可能比分、大小球、双方进球概率

### 📊 数据工具 (Function Calling)
| 工具 | 功能 |
|------|------|
| `search_matches` | 搜索联赛比赛 |
| `predict_match` | 预测比赛结果 |
| `get_standings` | 联赛积分榜 |
| `get_team_info` | 球队实力分析 |
| `analyze_head_to_head` | 历史交锋分析 |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | AI 对话接口 |
| POST | `/api/predict` | 快速预测接口 |
| GET | `/api/matches` | 比赛列表 |
| GET | `/api/standings/{league}` | 积分榜 |
| GET | `/api/health` | 健康检查 |

## 数据来源

- **football-data.org**: 免费额度每分钟10次请求，覆盖欧洲主流联赛
- **模拟数据**: 当未配置 API Key 时自动降级，内置英超20支球队数据
- **缓存**: 使用 diskcache 减少重复 API 请求
