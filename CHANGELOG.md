# Changelog

本项目的版本与里程碑对应关系：v0.1 = m1；v0.2 = m1 的错误路径加固；v0.3 = m1 的数据可信度加固（不新增能力）；m2/m3 在后续版本交付。

## 0.3.0 - 2026-11-24

数据可信度修复版（里程碑 **m1 的加固**）：不新增能力，只修「一次盲测会被
一条异常或一张模拟票毁掉」的三类缺陷，并把用户可见的版本声明收回到单一来源。

### 修复

- 单家模型的 API 调用失败（HTTP 401/5xx、60s 超时）不再让整轮盲测以
  `ProviderError` traceback 中止：`run` 只跳过涉及该模型的那一对、打印模型
  id 与「重跑会重试」的提示，其余对局照常投票；本轮所有对局都失败时退出码 1，
  不再是静默的成功。这也让 README 里「best-effort 模型失败不影响其余模型」
  的承诺真正成立。
- `--demo` 的模拟票不再混进真实盲测：每张票记录 `mode`（`live`/`demo`），
  真实 `run` 不会把演示票当成「已投票」而跳过那一对，`report`/`retest` 只统计
  真实票并在存在演示票时明确说明未计入。旧票仓（无 `mode` 字段）按 `live` 读取。
- 写坏的回答缓存（追加写中断留下的半行 JSON）不再让 `run` 以
  `JSONDecodeError` traceback 退出：缓存是派生状态，读不出就当作 cache miss
  重新请求并覆盖修复。

### 新增

- `tests/test_model_failure.py`、`tests/test_demo_votes.py`、
  `tests/test_answer_cache.py`：上述三类缺陷的红→绿回归测试。
- `tests/test_version_lockstep.py` 增加 `--version` 输出断言，并禁止
  `src/` 里残留「v0.1 尚未实现」这类会随版本漂移的能力声明。

### 已知边界

- 重测一致率信度分、BT 个人排名、噪声任务与报告导出仍在 m2 交付。
- 聚合榜单快照分数字段为 null（未抄录），分歧表待 m2。
- `--demo` 回答为确定性模拟内容，不代表任何真实模型表现；演示票单独标记，
  不计入真实首轮进度与胜率。

## 0.2.0 - 2026-10-21

错误路径修复版（里程碑 **m1 的加固**）：不新增能力，只修「非法输入与损坏状态
导致抛栈、或静默写入无意义数据」的四类缺陷，并把版本面绑进测试。

### 修复

- `run --models` 少于两家模型时不再抛出未捕获的 `ValueError`（原先打印内部
  调用栈），改为干净的报错与退出码 1。
- `run --models` 对重复 id 去重：`--models X,X` 原先会让同一家模型和自己盲测，
  票仓里落一条 `models.a == models.b` 的无意义选票；现在去重后按「至少两家不同
  模型」校验。
- `init --tasks` 的种子文件非法（kind 非法 / 缺 prompt / TOML 语法错误）不再
  抛栈，改为呈现 `intake` 已写好的解释性错误并退出 1。
- 票仓 `votes.jsonl` 损坏（追加写被中断留下的半行）时，`run` / `retest` /
  `report` 改为干净报错并退出 1，而不是让 `pydantic` 的校验异常抛到栈外。

### 新增

- `tests/test_version_lockstep.py`：把「单一来源 = `blindtaste.__version__`，
  其余描述当前版本的面（`pyproject.toml`、`web/site.json`、两个 README 徽章、
  CHANGELOG 条目）必须与它一致」固化成断言。
- `tests/test_cli_errors.py`：上面四条错误路径的回归测试（红→绿）。

### 已知边界

- 重测一致率信度分、BT 个人排名、噪声任务与报告导出在 m2 交付。
- 聚合榜单快照分数字段为 null（未抄录），分歧表待 m2。
- `--demo` 回答为确定性模拟内容，不代表任何真实模型表现。
- `docs/demo-results.json` 是 m1 录屏的历史记录，其 `implementation_version`
  保持 0.1.0（与 `recorded_at` / `milestone` 同属 provenance），不随本版上抬。

## 0.1.0 - 2026-09-15

首个发布（里程碑 **m1：盲测电池**）。

### 新增

- `blindtaste init`：8 道中文选择题生成 6-10 条任务电池（改简历 / 写周报 / PPT 大纲 / 翻译 + 自定义），`--tasks` 种子文件直建模式。
- `blindtaste run`：终端匿名 A/B 盲测（约 15 对），并排半宽面板对比，投票后揭晓模型；`--models` 覆盖参测模型，`--limit` 限量体验，`--demo` 离线模拟回答（不调用 API）。
- 票仓 `votes.jsonl`：追加式落盘、按 trial_id 去重、Ctrl-C 断点续跑；trial 由电池指纹确定性生成；回答缓存按（模式, 模型, 任务）复用。
- 五家官方 OpenAI 兼容端点接入（智谱 / DeepSeek / 百炼 / Kimi / 火山方舟），统一在 `ChatAdapter` 接口后；方舟（豆包）标记为未验证、best-effort。
- `blindtaste retest` / `report`：m2 占位命令，展示当前进度与票面统计。

### 已知边界

- 重测一致率信度分、BT 个人排名、噪声任务与报告导出在 m2 交付。
- 聚合榜单快照分数字段为 null（未抄录），分歧表待 m2。
- `--demo` 回答为确定性模拟内容，不代表任何真实模型表现。
