const items = {
  brainstorm: {
    topic: "Codex 交互知识库",
    judgement: "按项目沉淀 Codex 交互全过程",
    questions: "如何识别线程所属项目？没有项目的常规对话如何独立存储？后续如何把常规对话转入项目？",
    actions: "建立项目空间、常规对话空间、项目归属规则、转入项目动作和跨项目搜索。",
    title: "Codex 交互知识库"
  },
  doc: {
    topic: "Codex 交互知识库",
    judgement: "文件产物必须归属到项目线程，而不是单独漂在文件夹里。",
    questions: "如何记录文件版本？如何区分草稿和最终产物？如何回溯某个页面为什么这样设计？",
    actions: "为每个产物保存所属项目、来源线程、关键修改、截图验证、最终路径和可复用片段。",
    title: "产物索引与版本记忆"
  },
  meeting: {
    topic: "Codex 交互知识库",
    judgement: "同一个项目下的错误方向、用户纠偏和重新定义，需要形成项目内的过程链路。",
    questions: "哪些纠偏应该被标记为决策？如何从错误路径里提取可复用原则？",
    actions: "把纠偏点挂到项目线程下，形成下次产品定义时可复用的判断规则。",
    title: "需求纠偏过程"
  },
  question: {
    topic: "常规对话",
    judgement: "没有项目归属的普通问答需要单独存储，避免污染项目知识图谱。",
    questions: "常规对话保留多久？哪些内容应建议转入项目？转入项目后是否保留原始位置？",
    actions: "建立常规对话空间，并提供“转入项目”“设为长期知识”“到期清理”三类动作。",
    title: "常规对话存储规则"
  }
};

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
  });
});

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    button.parentElement.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
  });
});

document.querySelectorAll(".input-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".input-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");

    const data = items[button.dataset.item];
    document.getElementById("topic").textContent = data.topic;
    document.getElementById("judgement").textContent = data.judgement;
    document.getElementById("questions").textContent = data.questions;
    document.getElementById("actions").textContent = data.actions;
    document.getElementById("cardTitle").textContent = data.title;
  });
});
