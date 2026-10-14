# 知识库工作流

这里存放机器人可以引用的 Markdown 资料。为了避免把个人资料误发给客户，资料必须先进入草稿区，再由你逐份审阅后移动到公开区。

- `drafts/`：待人工审核的材料。程序永远不会读取这里，也不会提交到 Git。
- `approved/`：审核通过、可对外回答的材料。程序会按问题关键词抽取相关段落，作为大模型回答的事实来源；这里的实际资料同样不会提交到 Git。
- `private/`：个人原始资料或敏感备份。程序绝不读取，也不会提交到 Git。

不要把 API Key、客户聊天记录、身份证件、联系方式、行程或其他私人资料放进此目录。

每份资料建议写明来源、采集日期、可对外使用的信息和不应推断的信息。公开资料可使用以下开头：

```markdown
---
audience: public
source: 本人确认
updated: 2026-10-14
---
```

`audience` 不是 `public` 或 `external` 的资料，即使误放到 `approved/` 也不会被机器人检索。可参考
[`approved/profile-template.md`](approved/profile-template.md)。
