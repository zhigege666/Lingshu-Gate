# 完成第一次成功调用与拒绝调用

[English](../first-call.md) · [开始使用](getting-started.md) · [文档索引](README.md)

使用随包提供的内存 MCP 验证发现、发布、限权令牌和真实写入拒绝。它不需要外部账号，不执行数据库、文件系统命令或网络操作；进程退出后，便笺、版本和写入计数清空。

请先[安装 Gate、登录并修改初始密码](getting-started.md)。本流程使用现有 HTTP 工具，不需要另装桌面 MCP 客户端。

## 在 Gate 旁启动演示服务

原生包另开一个终端，在解压目录运行：

~~~bash
./lingshu-gate demo-server --host 127.0.0.1 --port 18880
~~~

Windows 使用 `.\lingshu-gate.exe demo-server --host 127.0.0.1 --port 18880`；源码使用 `uv run lingshu-gate demo-server --host 127.0.0.1 --port 18880`。验证期间保持进程运行。端口被占用会报错，不会自动换端口。

**下载的 Docker 本机试用包**，在解压目录执行：

~~~bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml -f examples/compose.demo.yaml up -d --no-build --wait --wait-timeout 120 core demo
~~~

**下载的生产部署包**，先完成 `DEPLOYMENT.md` / `DEPLOYMENT.zh-CN.md` 的镜像、HTTPS 入口和 bootstrap 配置，再执行：

~~~bash
docker compose --env-file .env -f compose.yaml -f examples/compose.demo.yaml up -d --no-build --wait --wait-timeout 120 core demo
~~~

源码 Compose 安装可显式启用示例覆盖文件：

~~~bash
mkdir -p runtime/workspace
docker compose -f compose.yaml -f examples/compose.demo.yaml up -d --build --wait --wait-timeout 120 core demo
~~~

命令等待 Core 与实际 demo 监听就绪。离线安装先载入匹配镜像，在选定的 env 文件中设置 `LINGSHU_GATE_PULL_POLICY=never`。演示服务与 Core 使用同一个镜像、共享网络命名空间，不新增宿主端口。普通独立容器不能通过服务名访问这个只监听回环地址的服务。

## 接入并发布

1. 管理员登录。全新实例先读取本地一次性凭据、修改密码并重新登录；旧会话被撤销，自动生成的初始凭据文件被删除。生产环境外部准备的密码文件继续由操作员管理。
2. 在 MCP 工作区，根据[演示配置](../../examples/mcp.d/demo.yaml)创建**外部 Streamable HTTP** 服务。分别进行校验、保存、应用和启动。地址为 `http://127.0.0.1:18880/mcp`，协议自动协商。
3. 发现三个工具。将 `gate_demo_echo`、`gate_demo_note_read` 审核为**只读、非破坏、幂等**。将 `gate_demo_note_write` 审核为**写入、非破坏、非幂等**，因为重复写入仍增加计数。
4. 确认分类审核，再单独发布。仅发现、保存配置或确认审核均不等于发布授权。

示例服务 ID 是 `demo`；若修改 ID，应使用自己目录返回的工具引用。

## 创建限权调用身份

建立独立的有效 viewer 用户，只授予演示服务的**读取**权限。以该用户登录，需要时先改密；创建功能范围为 `tools.read`、该 MCP 持续范围为**只读**的个人 API 令牌，发现方式保持**按需**，不添加固定工具。保存一次性显示的令牌，列表不会重新返回明文。

后续请求使用这个独立令牌。管理员自己的令牌不能证明限权效果。只将不含秘密的 JSON 请求体保存在仓库外的本地 `request.json`。Bash 本地终端用下面函数通过标准输入发送 bearer，避免秘密进入外部进程参数：

~~~bash
GATE_URL='http://127.0.0.1:8000'
read -rsp 'Demo viewer token: ' GATE_TOKEN
builtin export -n GATE_TOKEN
builtin printf '\n'
gate_request() {
  local method="$1" name="$2" body_file="$3"
  local -a headers=(-H 'Content-Type: application/json' -H 'Accept: application/json'
    -H 'MCP-Protocol-Version: 2026-07-28' -H "MCP-Method: $method")
  if [[ -n "$name" ]]; then headers+=(-H "MCP-Name: $name"); fi
  builtin printf 'Authorization: Bearer %s\n' "$GATE_TOKEN" |
    curl --fail-with-body --silent --show-error --connect-timeout 5 --max-time 30 "$GATE_URL/mcp" \
      --header @- "${headers[@]}" --data-binary "@$body_file"
}
~~~

HTTPS 部署将 `GATE_URL` 改为真实受信入口；修改本机端口时使用实际 URL。Bash 内置 `printf` 将授权头写入 curl 的 stdin，token 不展开到 curl argv，也不导出到子进程环境。不要开启 shell tracing。

Windows PowerShell 可直接发送相同 JSON，不需要另装客户端：

~~~powershell
$GateUrl = 'http://127.0.0.1:8000'
$SecureToken = Read-Host 'Demo viewer token' -AsSecureString
$GateToken = [System.Net.NetworkCredential]::new('', $SecureToken).Password
function Invoke-GateRequest([string]$Method, [string]$Name, [string]$BodyFile) {
    $Headers = @{
        Authorization = "Bearer $GateToken"
        Accept = 'application/json'
        'MCP-Protocol-Version' = '2026-07-28'
        'MCP-Method' = $Method
    }
    if ($Name) { $Headers['MCP-Name'] = $Name }
    $Body = [System.IO.File]::ReadAllText((Resolve-Path $BodyFile).Path)
    Invoke-RestMethod -Uri "$GateUrl/mcp" -Method Post -Headers $Headers `
        -ContentType 'application/json; charset=utf-8' -Body $Body |
        ConvertTo-Json -Depth 30
}
~~~

bearer 保留在 PowerShell 进程内存中。将 Bash 函数调用改为 `Invoke-GateRequest -Method 'tools/call' -Name 'gate_tool_describe' -BodyFile '.\request.json'`，根据步骤调整 method/name。`tools/list` 使用 `-Method 'tools/list' -Name ''`。这些 HTTP 示例不代表第三方桌面客户端已经实测。

## 发现、读取、尝试写入、复查计数

向 `$GATE_URL/mcp` 发送 JSON-RPC，使用这些请求头：

~~~text
Authorization: Bearer <viewer 令牌>
Content-Type: application/json
Accept: application/json
MCP-Protocol-Version: 2026-07-28
MCP-Method: tools/call
MCP-Name: <params.name>
~~~

`tools/call` 请求的 `MCP-Name` 必须匹配正文 `params.name`，`tools/list` 不发送该头。下例包含 2026-07-28 必需的 `params._meta`。每步把 JSON 写入 `request.json`，将引用、修订占位值替换为真实返回值，再用对应函数参数发送，例如：

~~~bash
gate_request tools/call gate_tool_describe request.json
~~~

调用时将第二个参数改为 `gate_tool_invoke`。curl 非零状态或 PowerShell 异常表示 HTTP 失败；HTTP 200 时仍须检查 JSON-RPC 错误和 `result.isError`。

**列出网关入口**，使用 `gate_request tools/list '' request.json`：

~~~json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

没有固定工具时，按需发现列出六个入口，包括 `gate_catalog_search`、`gate_tool_describe`、`gate_tool_invoke`。发现入口不授予下游权限。

**搜索有权目录**，使用 `gate_request tools/call gate_catalog_search request.json`：

~~~json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"gate_catalog_search","arguments":{"query":"gate_demo","limit":20},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

找到 `gate_demo_echo`、`gate_demo_note_read`，复制实际返回的 `tool_ref`。只读 viewer 的搜索结果中不应出现写工具。

**描述 `gate_demo_note_read`**，使用该工具真实返回的引用。下方空参数请求必须选择这个便笺读取工具；echo 需要 message 参数，随后单独验证：

~~~json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"gate_tool_describe","arguments":{"tool_ref":"<returned read tool_ref>"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

阅读输入 schema，将该工具返回的 64 字符 `schema_revision` 填入调用：

~~~json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"gate_tool_invoke","arguments":{"tool_ref":"<returned read tool_ref>","schema_revision":"<returned revision>","arguments":{}},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

成功结果含 `text`、`revision`、`write_count`，记下计数。

验证 echo 时描述它自己的返回引用，再用它自己的修订及 `arguments: {"message":"Hello from Gate"}` 调用，确认返回消息与输入一致。以 viewer 打开 **My invocations / 我的调用**，核对成功的实际 demo 工具与结果；管理员在调用审计中查看对应记录。审计决策不需要开启可选的调用内容记录，本流程不会启用该功能。

验证真实权限拒绝时，在另一个管理员终端和授权中搜索、描述写工具，只把实际引用和当前修订交给演示操作员。发送拒绝调用的终端始终使用 **viewer 令牌**：

~~~json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"gate_tool_invoke","arguments":{"tool_ref":"<write reference from administrator>","schema_revision":"<current write-tool revision>","arguments":{"text":"This write must be denied"}},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
~~~

Gate 应返回 MCP 错误 `isError: true`；HTTP 200 不代表执行成功。重复读取，便笺与 `write_count` 应保持不变。管理员可在对应调用审计中查看拒绝和 `not_invoked`。没有权限的调用者不能通过描述隐藏工具获取其版本。

## 检查修订变化、停服与撤销

复制合法读请求，在 64 字符的 `schema_revision` 中修改一个十六进制字符，确保不同于当前值。调用应返回 `catalog_schema_revision_conflict`，不执行下游。这个故意不匹配的值用于验证守卫；实际定义变化后，应重新 describe 有权工具并审阅新 schema，再接受当前修订。恢复真实修订并确认读调用成功。

在 viewer 令牌仍有效时停止 demo。下载的 Docker 本机试用执行：

~~~bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml -f examples/compose.demo.yaml stop demo
~~~

生产使用 `.env` 和 `compose.yaml`；源码 Compose 保留原来的两个文件。原生在 demo 终端 Ctrl+C。再次正确读取，查看 MCP 错误、服务状态和调用结果。目录或恢复失败可能包含结构化错误码；传输连接失败也可能只返回 `isError: true` 和文本 `content`。核对对应的失败调用审计；工具已离开注册表时，核对目录拒绝事件。Gate 自身 `/readyz` 仍应正常。停止或断连可能使工具离开可调用目录；任何分支都不应返回缓存的成功便签。

用原命令重启 demo，必要时在 Gate 重新连接已保存服务。再次 search/describe，用当前读合同调用。定义未变时保留已发布审核，demo 内存便签与计数重置；定义改变需要重新审核、发布后才能使用。

最后在 **My authorizations / 我的授权** 撤销 viewer 令牌，用相同 bearer 重试，必须认证失败；明确失效的 bearer 不会回退到 Console cookie。终端用 `unset GATE_TOKEN` 清理凭据，`unset -f gate_request` 移除函数。PowerShell 使用 `$GateToken = $null; $SecureToken.Dispose(); Remove-Variable GateToken, SecureToken; Remove-Item Function:\Invoke-GateRequest`。

## 排查

| 现象 | 检查 |
|---|---|
| 无法连接 | 演示进程、共享网络命名空间、精确地址及 Gate 服务状态 |
| 目录为空或缺工具 | 分类是否发布、账号资源授权、令牌功能范围及 MCP 选择 |
| 合同版本被拒绝 | 重新描述当前可见工具，审核变更后的定义 |
| 拒绝调用看起来成功 | 查看 `isError` 或工具错误，不能只看 HTTP 200 |
| 客户端目录未变化 | 修改发现设置后刷新工具缓存或重连 |
| 计数增加 | 是否使用了独立 viewer 令牌，是否有其他调用者并发写入 |

演示结束后停止独立 demo。Gate 保留服务配置；按包内 README 停止 Gate 并保留数据。
