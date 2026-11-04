# Lingshu Gate 0.5.10

## English

0.5.10 fixes a side effect in SQLite readiness checks. If the main database file disappears after startup, `GET /readyz` reports HTTP 503 without creating an empty replacement. In a 0.5.9 reproduction, the response was already 503, but the probe left a 4 KiB file at the missing path.

### Changes

The database check opens only an existing file and reads the baseline migration on one read-only connection. It does not switch journal mode and continues to honor SQLite locking, including when committed data is in the write-ahead log (WAL).

### Upgrade and compatibility

No runtime dependency or schema migration is added over 0.5.9. Normal startup can still create a database, apply migrations and open writable business connections. MCP request handling, authorization and configuration-directory readiness are unchanged.

### Validation and known limits

A regression check must inspect both the HTTP status and the database path: with the probe isolated on a disposable instance, repeated requests against a missing main file should return 503 and leave the path absent. A readable baseline should pass; the check should also see committed changes in an active WAL, including removal of the baseline record.

Other Gate connections or external processes can still create the main database. SQLite may access or create the `-wal` and `-shm` files. The probe does not test future writes or restore data. If the main file disappears, check the mount before restarting; use a consistent backup for recovery.

See [operator guidance](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.10/docs/operations.md), [deployment and backup](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.10/docs/deployment.md), [changes](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.10/CHANGELOG.md) and [release verification](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.10/docs/releases.md).

## 简体中文

0.5.10 修复 SQLite 就绪检查的副作用。主库文件在启动后消失时，`GET /readyz` 返回 HTTP 503，不会创建空的替代文件。在一次 0.5.9 复现中，响应已经是 503，但探针仍在原路径留下了一个 4 KiB 文件。

### 变更

数据库检查只打开已有文件，使用一个只读连接读取基线迁移记录。探针不切换日志模式，遵循 SQLite 锁机制；已提交的数据仍在预写日志（WAL）中时也按正常规则读取。

### 升级与兼容

相对 0.5.9 不新增运行依赖或数据库迁移。正常启动仍可建库、应用迁移，业务连接仍可写入。MCP 请求处理、授权和配置目录就绪检查不变。

### 验证与已知边界

回归验证需要同时核对 HTTP 状态和数据库路径：在可丢弃的实例上单独运行探针，主库文件缺失时重复请求就绪接口应持续返回 503，原路径也应持续缺失。基线记录可读时数据库检查应通过；检查也应读到活动 WAL 中已提交的变更，包括基线记录已被删除。

常规业务连接或外部进程仍可能创建主库，SQLite 也可能访问或创建 `-wal` 和 `-shm` 文件。探针不测试后续写入，也不恢复数据。主库文件消失时，应在重启前核对挂载；恢复数据应使用一致备份。

参见[运维说明](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.10/docs/zh-CN/operations.md)、[部署与备份](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.10/docs/zh-CN/deployment.md)、[变更记录](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.10/CHANGELOG.zh-CN.md)和[发行验证](https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.10/docs/zh-CN/releases.md)。
