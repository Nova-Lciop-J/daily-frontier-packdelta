# PackDelta：检查实际要发布的 npm 包发生了什么变化

面向 npm 包维护者与发布审核者。输入前后两个 `.tgz`，离线比较真正发货的
文件，而不只是 Git 源码。突出安装脚本、依赖声明、入口、Source Map 和可执行
权限变化；还会检查候选包里未变化的可疑敏感文件名。不会执行脚本、安装包、
解压文件到磁盘、读取凭据或访问网络。

区别：`npm diff` 已经能比较文件补丁，`npm pack --dry-run` 可预览文件，
diffoscope 提供全面产物比较。本项目不是其替代品，重点是零依赖、有限资源的
两包发布审核摘要、结构化 JSON 和可用于 CI 的退出码。不声称“全球首创”。
2026-09-18 npm 发布 stage-only token 增加了审核实际候选包的场景，但本项目
没有接入或验证 npm staging API，也不需要该服务。

## 安装与演示

已准备验证环境为 Linux / Python 3.13.15；其他系统和版本尚未验证。
预装 Python 后无需 pip、外网、API Key 或付费服务。在项目目录运行：

```sh
python3 -m venv --without-pip .venv
.venv/bin/python tools/build_zipapp.py
.venv/bin/python examples/make_demo.py
.venv/bin/python dist/packdelta.pyz dist/demo/before.tgz dist/demo/after.tgz --fail-on never
.venv/bin/python -m unittest discover -s tests -v
```

预期看到增加两个文件、一个文件修改、一个文件保持不变，并提示 `postinstall`
脚本变化及新增 Source Map。样例完全合成，但实际比较真实生成的压缩包，
不是硬编码报告。`--fail-on never` 仅为方便展示故意加入的问题；实际审核默认
使用 `--fail-on review`。错误输入即使在 never 模式仍返回 2。

## 实际使用

```sh
python3 dist/packdelta.pyz before.tgz after.tgz --format json > report.json
```

退出码：0 表示未触发指定审核条件，1 表示需要审核，2 表示输入或用法错误。
可选 `--fail-on high`、`--fail-on change`。无问题信号不等于安全认证。
报告绑定两个输入的 SHA-256，不输出脚本内容或依赖地址，但文件名与字段名
仍可能敏感，公开前仍需人工审查。

可以另外在可信的合成/自有样例目录运行 `npm pack --ignore-scripts --offline`
得到真实 npm 产物。该命令不执行生命周期脚本，也不会替你构建缺失产物。
PackDelta 不调用 npm。不在带凭据的环境中执行不可信包。

## 边界、许可与维护

仅支持 `package/` 下的 gzip/tar；拒绝目录穿越、符号/硬链接、特殊文件和重复
路径。限制压缩输入 16 MiB、解压流 64 MiB、单文件 8 MiB、有效载荷总计 32 MiB、
2,000 项和 128 KiB 的 package.json。并不提供恶意代码判定、秘密内容扫描、
嵌套压缩包扫描、签名验证、传递依赖漏洞审计或语义兼容性证明。

MIT 许可、无第三方源码及真实业务数据。目标仓库许可兼容性仍需发布前核实。
每次修改应重新执行自动测试、构建与演示。当前版本为未发布候选，不宣称远程
CI、漏洞数据库审计或 npm staging 集成已经通过。详见英文 README、SECURITY、
MAINTENANCE 与 THIRD_PARTY 文件。
