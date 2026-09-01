# Azure SQL 建表指南

目标服务器：**`hkrl8282.database.windows.net`**

## 1. 创建数据库（若尚未创建）

在 Azure Portal → SQL Server `hkrl8282` → Databases → Create，例如数据库名：

```
13f-analyzer
```

## 2. 配置防火墙

SQL Server → **Networking**：

- 开启 **Allow Azure services and resources to access this server**（Static Web App / Functions 需要）
- 若在本机跑 pipeline，添加您电脑的公网 IP

## 3. 执行建表脚本

项目中的 `database/schema.sql` 会创建以下 8 张表：

| 表名 | 用途 |
|------|------|
| `funds` | 基金列表（名称、类型、CIK） |
| `filings` | 13F 申报记录 |
| `holdings` | 季度持仓明细 |
| `securities` | 证券主数据 |
| `daily_prices` | yfinance 日线行情 |
| `portfolio_snapshots` | 组合权重快照 |
| `backtest_results` | 季度回测结果 |
| `sync_log` | 数据同步日志 |

### 方式 A：Azure Portal Query Editor

1. 打开数据库 → **Query editor**
2. 登录（SQL authentication）
3. 粘贴 `database/schema.sql` 全文并执行

### 方式 B：本机 sqlcmd

```bash
sqlcmd -S hkrl8282.database.windows.net -d 13f-analyzer -U YOUR_USER -P 'YOUR_PASSWORD' -i database/schema.sql
```

## 4. 配置连接字符串

将 `YOUR_USER`、`YOUR_PASSWORD`、`YOUR_DATABASE` 替换为实际值：

```
mssql+pyodbc://YOUR_USER:YOUR_PASSWORD@hkrl8282.database.windows.net/13f-analyzer?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
```

写入位置：

| 场景 | 配置文件 |
|------|----------|
| 本地 pipeline | 项目根目录 `.env` |
| 本地 API | `api/local.settings.json` → `DATABASE_URL` |
| 生产环境 | Azure Static Web App → Configuration → `DATABASE_URL` |
| GitHub Actions 同步（若启用） | GitHub Secrets → `DATABASE_URL` |

## 5. 验证连接

```bash
cd pipeline
pip install -r requirements.txt
cp ../.env.example ../.env   # 编辑填入真实密码
python -c "from db import get_connection; conn=get_connection().__enter__(); print('OK')"
```

## 6. 灌入数据

```bash
python sync_all.py
```

会先 seed `data/funds.json` 中的 32 支基金，再拉 EDGAR 13F、yfinance 股价并计算回测。
