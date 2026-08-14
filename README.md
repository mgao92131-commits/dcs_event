# DCS 日志 SQLite 存储层 V1

本目录提供 `EVENTS.txt` 到 SQLite `events` 表的原始事件存储，不包含报警、模式或其他业务分析。

## 使用

```powershell
python dcsdb.py import EVENTS.txt
python dcsdb.py query --module PICA-117024 --limit 20
python dcsdb.py query --parameter PID1/MODE.TARGET --from "2026-08-01" --to "2026-08-14"
python dcsdb.py status
python dcsdb.py check
python dcsdb.py backup
```

默认路径为：

- 数据库：`data/dcs_events.db`
- 导入错误日志：`logs/import.log`
- 备份目录：`backup/`

`query --to` 使用左闭右开时间范围；日期形式的 `--to 2026-08-14` 表示截至该日 00:00:00，不包含 14 日当天。

可用 `--db` 和 `import --log` 覆盖默认路径。编码按 `utf-8-sig`、`gb18030` 顺序识别；表头错误和编码错误会终止导入，单行时间或列数错误会记录到 `import.log` 并跳过。

## 代码结构

- `dcsdb/parser.py`：编码、表头、TAB 文件和时间解析
- `dcsdb/hasher.py`：事件级 SHA-256 去重
- `dcsdb/schema.py`：`events` 表、索引和 `user_version=1`
- `dcsdb/importer.py`：5000 条批量、单事务导入
- `dcsdb/repository.py`：面向后续分析模块的查询接口
- `dcsdb/db.py`：SQLite PRAGMA、状态、检查和备份
- `dcsdb.py`：命令行入口

测试：

```powershell
python -m unittest discover -s tests -v
```
