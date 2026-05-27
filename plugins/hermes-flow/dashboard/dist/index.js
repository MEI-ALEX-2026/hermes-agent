(function () {
  const root = document.createElement("div");
  root.className = "hf-root";
  let pollTimer = null;
  let ws = null;
  let drag = null;
  let state = {
    projects: [],
    selectedProject: "",
    agentTemplates: [],
    bindings: [],
    workflows: [],
    selected: null,
    runs: [],
    status: null,
    logRunId: "",
    logs: [],
    runDetails: null,
    ptySessions: [],
    approvals: [],
    editingTaskId: "",
    editingEdgeId: "",
    locale: "en",
  };

  const I18N = {
    en: {
      title: "Flow",
      subtitle: "Turn a development goal into a guided workflow: draft, confirm, queue, observe, and resume.",
      refresh: "Refresh",
      workerMissing: "Worker offline · run hermes flow daemon",
      worker: "Worker",
      active: "active",
      running: "running",
      start: "Start",
      createProject: "Create project",
      projectName: "Project name",
      rootDir: "Repository path",
      projectHint: "Create a project first. Workflows, templates, runs, and logs will stay scoped to it.",
      templates: "Templates",
      workflows: "Workflows",
      runs: "Runs",
      noRuns: "No runs yet",
      noWorkflows: "No project workflows yet",
      useTemplate: "Use template",
      selectedTemplate: "Template preview",
      templateHelp: "Copy this template into a project before editing or running it.",
      draftGoal: "Describe the change you want",
      createDraft: "Draft workflow",
      project: "Project",
      tasks: "Tasks",
      edges: "Edges",
      guardrails: "Guardrails",
      status: "Status",
      confirm: "Confirm",
      queueRun: "Queue run",
      readyToRun: "Ready to run",
      draftNeedsConfirm: "Confirm the workflow before queueing it.",
      canvasEmptyTitle: "No tasks yet",
      canvasEmptyBody: "Add the first task or draft a workflow from the left panel.",
      nextStep: "Next step",
      taskEditor: "Task",
      edgeEditor: "Edge",
      addTask: "Add task",
      saveTask: "Save task",
      addEdge: "Add edge",
      saveEdge: "Save edge",
      taskTitle: "Task title",
      taskGoal: "Task goal",
      criteria: "Acceptance criteria",
      parentTask: "Parent task",
      failureTask: "Failure fallback",
      noParentTask: "No parent",
      noFailureTask: "No failure fallback",
      executor: "Executor",
      aiAgent: "Hermes AI Agent",
      cliExecutor: "CLI",
      taskDetails: "Task details",
      newTask: "New task",
      source: "Source",
      target: "Target",
      route: "Route",
      observations: "Observe",
      noPty: "No PTY takeover session",
      selectRun: "Select a run to inspect logs",
      approvals: "Approvals",
      noApprovals: "No pending approvals",
      logs: "Logs",
      allowOnce: "Allow once",
      allowRun: "Allow run",
      deny: "Deny",
      pause: "Pause",
      resume: "Resume",
      cancel: "Cancel",
      send: "Send",
      ptyInput: "Input to active PTY",
      agentTemplates: "Agents",
      executorSetup: "Execution setup",
      noAgents: "No agent templates",
      saveAgent: "Save agent",
      agentName: "Agent name",
      command: "Command or profile",
      bindings: "Bindings",
      bind: "Bind",
      role: "Role",
      selectProject: "Select a project to bind agents.",
    },
    zh: {
      title: "Flow",
      subtitle: "把开发目标变成可执行流程：起草、确认、排队、观察、接管和恢复。",
      refresh: "刷新",
      workerMissing: "Worker 未连接 · 运行 hermes flow daemon",
      worker: "Worker",
      active: "活跃",
      running: "运行中",
      start: "开始",
      createProject: "创建项目",
      projectName: "项目名称",
      rootDir: "仓库路径",
      projectHint: "先创建项目。工作流、模板副本、运行记录和日志都会归属到项目下。",
      templates: "模板",
      workflows: "工作流",
      runs: "运行记录",
      noRuns: "暂无运行记录",
      noWorkflows: "还没有项目工作流",
      useTemplate: "使用模板",
      selectedTemplate: "模板预览",
      templateHelp: "模板需要先复制到项目里，才能编辑和运行。",
      draftGoal: "描述你想完成的改动",
      createDraft: "生成草稿",
      project: "项目",
      tasks: "任务",
      edges: "连线",
      guardrails: "护栏",
      status: "状态",
      confirm: "确认流程",
      queueRun: "加入队列",
      readyToRun: "可以运行",
      draftNeedsConfirm: "运行前需要先确认工作流。",
      canvasEmptyTitle: "还没有任务",
      canvasEmptyBody: "添加第一个任务，或从左侧输入目标生成草稿。",
      nextStep: "下一步",
      taskEditor: "任务",
      edgeEditor: "连线",
      addTask: "添加任务",
      saveTask: "保存任务",
      addEdge: "添加连线",
      saveEdge: "保存连线",
      taskTitle: "任务标题",
      taskGoal: "任务目标",
      criteria: "验收标准",
      parentTask: "任务父节点",
      failureTask: "任务失败后执行",
      noParentTask: "无父节点",
      noFailureTask: "无失败节点",
      executor: "执行方式",
      aiAgent: "Hermes AI Agent",
      cliExecutor: "CLI",
      taskDetails: "任务详情",
      newTask: "新建任务",
      source: "起点",
      target: "终点",
      route: "路由",
      observations: "观察",
      noPty: "暂无 PTY 接管会话",
      selectRun: "选择运行记录查看日志",
      approvals: "审批",
      noApprovals: "暂无待审批事项",
      logs: "日志",
      allowOnce: "允许一次",
      allowRun: "本次运行允许",
      deny: "拒绝",
      pause: "暂停",
      resume: "恢复",
      cancel: "取消",
      send: "发送",
      ptyInput: "输入到当前 PTY",
      agentTemplates: "执行器",
      executorSetup: "执行设置",
      noAgents: "暂无执行器模板",
      saveAgent: "保存执行器",
      agentName: "执行器名称",
      command: "命令或 profile",
      bindings: "绑定",
      bind: "绑定",
      role: "角色",
      selectProject: "选择项目后再绑定执行器。",
    },
  };

  function copy() {
    return String(state.locale || "").startsWith("zh") ? I18N.zh : I18N.en;
  }

  function api(path, options) {
    const token = window.__HERMES_SESSION_TOKEN__ || "";
    const headers = { "Content-Type": "application/json" };
    if (token) headers["X-Hermes-Session-Token"] = token;
    return fetch("/api/plugins/hermes-flow" + path, {
      credentials: "same-origin",
      headers,
      ...(options || {}),
    }).then((res) => {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  function render() {
    const t = copy();
    const workflows = visibleWorkflows();
    const templates = templateWorkflows();
    root.innerHTML = [
      '<section class="hf-shell">',
      '<header class="hf-header">',
      '<div><h1>' + esc(t.title) + '</h1><p>' + esc(t.subtitle) + '</p></div>',
      '<div class="hf-actions"><span class="hf-status">' + statusText() + '</span><button class="hf-refresh" type="button">' + esc(t.refresh) + '</button></div>',
      "</header>",
      '<div class="hf-grid">',
      '<aside class="hf-list">',
      '<div class="hf-step"><span>1</span><strong>' + esc(t.project) + '</strong></div>',
      '<form class="hf-project-form"><input name="name" placeholder="' + esc(t.projectName) + '" /><input name="root_dir" placeholder="' + esc(t.rootDir) + '" /><button type="submit">' + esc(t.createProject) + '</button></form>',
      projectList(),
      '<div class="hf-step"><span>2</span><strong>' + esc(t.start) + '</strong></div>',
      '<form class="hf-draft"><input name="goal" placeholder="' + esc(t.draftGoal) + '" /><button type="submit">' + esc(t.createDraft) + '</button></form>',
      '<h2>' + esc(t.templates) + '</h2>',
      templates.map(workflowButton).join("") || '<div class="hf-empty">' + esc(t.noWorkflows) + '</div>',
      '<h2>' + esc(t.workflows) + '</h2>',
      workflows.map(workflowButton).join("") || '<div class="hf-empty">' + esc(t.noWorkflows) + '</div>',
      '<h2>' + esc(t.runs) + '</h2>',
      (state.runs || []).slice(0, 6).map(runRow).join("") || '<div class="hf-empty">' + esc(t.noRuns) + '</div>',
      "</aside>",
      '<main class="hf-main">',
      state.selected ? workflowView(state.selected) : welcomeView(),
      "</main>",
      "</div>",
      "</section>",
    ].join("");
    bindEvents();
  }

  function agentTemplateList() {
    const t = copy();
    const templates = state.agentTemplates || [];
    if (!templates.length) return '<div class="hf-empty">' + esc(t.noAgents) + '</div>';
    return '<div class="hf-mini-list">' + templates.map((template) => '<span>' + esc(template.name) + " · " + esc(template.type) + "</span>").join("") + "</div>";
  }

  function bindingForm() {
    const t = copy();
    const templates = state.agentTemplates || [];
    const options = templates.map((template) => '<option value="' + esc(template.id) + '">' + esc(template.name) + " · " + esc(template.type) + "</option>").join("");
    return [
      '<form class="hf-binding-form">',
      '<input name="role" placeholder="' + esc(t.role) + '" />',
      '<select name="agent_template_id">' + options + "</select>",
      '<button type="submit"' + (!templates.length || !state.selectedProject ? " disabled" : "") + ">" + esc(t.bind) + "</button>",
      "</form>",
    ].join("");
  }

  function bindingList() {
    const t = copy();
    const bindings = state.bindings || [];
    if (!state.selectedProject) return '<div class="hf-empty">' + esc(t.selectProject) + '</div>';
    if (!bindings.length) return '<div class="hf-empty">' + esc(t.selectProject) + '</div>';
    return '<div class="hf-mini-list">' + bindings.map((binding) => '<button type="button" data-binding-id="' + esc(binding.id) + '">' + esc(binding.role || "default") + " · " + esc(binding.agent_template_name || binding.agent_template_id) + "</button>").join("") + "</div>";
  }

  function workflowButton(wf) {
    const selected = state.selected && state.selected.id === wf.id ? " hf-active" : "";
    return '<button class="hf-workflow' + selected + '" data-id="' + esc(wf.id) + '"><strong>' + esc(displayWorkflowName(wf)) + '</strong><span>' + esc(workflowMeta(wf)) + '</span></button>';
  }

  function projectList() {
    const t = copy();
    const projects = state.projects || [];
    if (!projects.length) return '<div class="hf-empty hf-empty-compact">' + esc(t.projectHint) + '</div>';
    return projects
      .map((project) => {
        const active = state.selectedProject === project.id ? " hf-active" : "";
        return '<button class="hf-project' + active + '" data-project-id="' + esc(project.id) + '"><strong>' + esc(project.name) + '</strong><span>' + esc(project.root_dir) + "</span></button>";
      })
      .join("");
  }

  function runRow(run) {
    return '<button class="hf-run-row" data-run-id="' + esc(run.id) + '"><strong>' + esc(run.status) + '</strong><span>' + esc(run.id) + '</span></button>';
  }

  function welcomeView() {
    const t = copy();
    return [
      '<section class="hf-welcome">',
      '<div class="hf-welcome-copy"><h2>' + esc(t.createProject) + '</h2><p>' + esc(t.projectHint) + '</p></div>',
      '<div class="hf-guide">',
      '<div><strong>1</strong><span>' + esc(t.createProject) + '</span></div>',
      '<div><strong>2</strong><span>' + esc(t.createDraft) + '</span></div>',
      '<div><strong>3</strong><span>' + esc(t.confirm) + ' / ' + esc(t.queueRun) + '</span></div>',
      '</div>',
      '</section>',
    ].join("");
  }

  function workflowView(wf) {
    const t = copy();
    const tasks = wf.tasks || [];
    const edges = wf.edges || [];
    const isTemplate = Boolean(wf.template_key);
    return [
      '<div class="hf-toolbar">',
      '<div><h2>' + esc(displayWorkflowName(wf)) + '</h2><p>' + esc(displayWorkflowGoal(wf)) + '</p><div class="hf-meta-row"><span class="hf-pill">' + esc(isTemplate ? t.selectedTemplate : displayStatus(wf.status || "confirmed")) + '</span><span>' + esc(tasks.length) + ' ' + esc(t.tasks) + '</span><span>' + esc(edges.length) + ' ' + esc(t.edges) + '</span></div></div>',
      "</div>",
      '<div class="hf-workspace">',
      isTemplate ? templateCanvas(wf) : canvasView(tasks, edges),
      '<aside class="hf-editor">' + contextPanel(wf),
      "</aside>",
      "</div>",
    ].join("");
  }

  function workflowActions(wf) {
    const t = copy();
    if (wf.template_key) return '<button class="hf-use-template" type="button">' + esc(t.useTemplate) + '</button>';
    if ((wf.status || "confirmed") !== "confirmed") return '<button class="hf-confirm" type="button">' + esc(t.confirm) + '</button>';
    return '<button class="hf-run" type="button">' + esc(t.queueRun) + '</button>';
  }

  function nodeView(task) {
    const tasks = (state.selected && state.selected.tasks) || [];
    const position = displayTaskPosition(task, tasks.indexOf(task), tasks);
    const active = state.editingTaskId === task.id ? " hf-node-active" : "";
    return [
      '<button class="hf-node' + active + '" data-task-id="' + esc(task.id) + '" style="left:' + position.x + 'px;top:' + position.y + 'px">',
      '<strong>' + esc(displayTaskTitle(task)) + "</strong>",
      '<span>' + esc(displayStatus(task.status)) + "</span>",
      "</button>",
    ].join("");
  }

  function canvasView(tasks, edges) {
    if (!tasks.length) return '<div class="hf-canvas">' + canvasEmpty() + "</div>";
    const size = canvasSize(tasks);
    return [
      '<div class="hf-canvas">',
      '<div class="hf-canvas-inner" style="width:' + size.width + 'px;height:' + size.height + 'px">',
      edgeOverlay(edges, tasks, size),
      tasks.map(nodeView).join(""),
      "</div>",
      "</div>",
    ].join("");
  }

  function canvasSize(tasks) {
    const maxX = Math.max(720, ...tasks.map((task, index) => displayTaskPosition(task, index, tasks).x + 260));
    const maxY = Math.max(420, ...tasks.map((task, index) => displayTaskPosition(task, index, tasks).y + 150));
    return { width: maxX, height: maxY };
  }

  function displayTaskPosition(task, index, tasks) {
    if ((task.metadata || {}).manual_position) {
      return { x: Number(task.position_x || 0), y: Number(task.position_y || 0) };
    }
    const key = (task.metadata && task.metadata.template_task_key) || String(task.title || "").toLowerCase();
    const templatePositions = {
      implement: { x: 0, y: 0 },
      test: { x: 250, y: 0 },
      fix: { x: 250, y: 145 },
      complete: { x: 500, y: 0 },
      reproduce: { x: 0, y: 0 },
      patch: { x: 250, y: 0 },
      validate: { x: 500, y: 0 },
      review: { x: 250, y: 145 },
      update_docs: { x: 0, y: 0 },
    };
    if (templatePositions[key]) return templatePositions[key];
    const safeIndex = Math.max(0, index || 0);
    const columns = (tasks || []).length <= 2 ? 2 : 3;
    return {
      x: (safeIndex % columns) * 250,
      y: Math.floor(safeIndex / columns) * 145,
    };
  }

  function edgeOverlay(edges, tasks, size) {
    const byId = {};
    tasks.forEach((task) => {
      byId[task.id] = task;
    });
    const paths = (edges || [])
      .map((edge) => {
        const source = byId[edge.source_task_id];
        const target = byId[edge.target_task_id];
        if (!source || !target) return "";
        const sourcePos = displayTaskPosition(source, tasks.indexOf(source), tasks);
        const targetPos = displayTaskPosition(target, tasks.indexOf(target), tasks);
        const sx = sourcePos.x + 210;
        const sy = sourcePos.y + 42;
        const tx = targetPos.x;
        const ty = targetPos.y + 42;
        const mid = Math.max(36, Math.abs(tx - sx) / 2);
        const cls = edge.edge_type === "failure" ? "hf-edge-failure" : "hf-edge-success";
        return '<path class="' + cls + '" d="M ' + sx + " " + sy + " C " + (sx + mid) + " " + sy + ", " + (tx - mid) + " " + ty + ", " + tx + " " + ty + '" marker-end="url(#hf-arrow)" />';
      })
      .join("");
    return [
      '<svg class="hf-edge-svg" width="' + size.width + '" height="' + size.height + '" viewBox="0 0 ' + size.width + " " + size.height + '" aria-hidden="true">',
      '<defs><marker id="hf-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>',
      paths,
      "</svg>",
    ].join("");
  }

  function templateCanvas(wf) {
    const tasks = wf.tasks || [];
    if (!tasks.length) return '<div class="hf-template-flow">' + canvasEmpty() + '</div>';
    return '<div class="hf-template-flow">' + tasks.map((task, index) => [
      '<div class="hf-template-step">',
      '<span>' + String(index + 1) + '</span>',
      '<strong>' + esc(displayTaskTitle(task)) + '</strong>',
      '<em>' + esc(displayStatus(task.status || "draft")) + '</em>',
      '</div>',
    ].join("")).join("") + '</div>';
  }

  function contextPanel(wf) {
    const t = copy();
    if (wf.template_key) {
      return [
        '<section class="hf-panel-section hf-next">',
        '<h3>' + esc(t.nextStep) + '</h3>',
        '<p>' + esc(t.templateHelp) + '</p>',
        '<button class="hf-use-template hf-wide" type="button">' + esc(t.useTemplate) + '</button>',
        '</section>',
        '<section class="hf-panel-section"><h3>' + esc(t.tasks) + '</h3>' + taskSummaryList(wf) + '</section>',
      ].join("");
    }
    return [
      '<section class="hf-panel-section hf-next">',
      '<h3>' + esc(t.nextStep) + '</h3>',
      '<p>' + esc((wf.status || "confirmed") === "confirmed" ? t.readyToRun : t.draftNeedsConfirm) + '</p>',
      workflowActions(wf),
      '</section>',
      '<section class="hf-panel-section"><h3>' + esc(t.taskDetails) + '</h3>' + taskForm(wf) + '</section>',
    ].join("");
  }

  function agentTemplateForm() {
    const t = copy();
    return [
      '<form class="hf-agent-template-form">',
      '<input name="name" placeholder="' + esc(t.agentName) + '" />',
      '<select name="type"><option value="hermes_cli">Hermes CLI</option><option value="pty_cli">PTY CLI</option></select>',
      '<input name="command" placeholder="' + esc(t.command) + '" />',
      '<button type="submit">' + esc(t.saveAgent) + '</button>',
      '</form>',
    ].join("");
  }

  function canvasEmpty() {
    const t = copy();
    return '<div class="hf-canvas-empty"><strong>' + esc(t.canvasEmptyTitle) + '</strong><span>' + esc(t.canvasEmptyBody) + '</span></div>';
  }

  function taskSummaryList(wf) {
    const tasks = wf.tasks || [];
    if (!tasks.length) return canvasEmpty();
    return '<div class="hf-task-summary">' + tasks.map((task, index) => '<div><span>' + String(index + 1) + '</span><strong>' + esc(displayTaskTitle(task) || task.id) + '</strong><em>' + esc(displayStatus(task.status || "draft")) + '</em></div>').join("") + '</div>';
  }

  function taskForm(wf) {
    const t = copy();
    const task = findTask(state.editingTaskId) || {};
    const parentId = parentTaskId(task.id);
    const failureId = failureTaskId(task.id);
    const executorMode = ((task.metadata || {}).executor_mode) || ((task.validation_commands || []).length ? "cli" : "ai_agent");
    return [
      '<form class="hf-task-form">',
      '<label><span>' + esc(t.taskTitle) + '</span><input name="title" required value="' + esc(taskFormTitle(task)) + '" /></label>',
      '<label><span>' + esc(t.taskGoal) + '</span><textarea name="goal">' + esc(taskFormGoal(task)) + "</textarea></label>",
      '<label><span>' + esc(t.criteria) + '</span><textarea name="acceptance_criteria">' + esc(task.acceptance_criteria || "") + "</textarea></label>",
      '<label><span>' + esc(t.parentTask) + '</span><select name="parent_task_id">' + taskOptions(wf.tasks || [], task.id, parentId, t.noParentTask) + "</select></label>",
      '<label><span>' + esc(t.failureTask) + '</span><select name="failure_task_id">' + taskOptions(wf.tasks || [], task.id, failureId, t.noFailureTask) + "</select></label>",
      '<label><span>' + esc(t.executor) + '</span><select name="executor_mode"><option value="ai_agent"' + selected("ai_agent", executorMode) + ">" + esc(t.aiAgent) + '</option><option value="cli"' + selected("cli", executorMode) + ">" + esc(t.cliExecutor) + "</option></select></label>",
      '<div class="hf-form-actions"><button class="hf-secondary hf-new-task" type="button">' + esc(t.newTask) + '</button><button type="submit">' + esc(state.editingTaskId ? t.saveTask : t.addTask) + "</button></div>",
      "</form>",
    ].join("");
  }

  function taskOptions(tasks, currentTaskId, selectedTaskId, emptyLabel) {
    return '<option value="">' + esc(emptyLabel) + '</option>' + tasks
      .filter((task) => task.id !== currentTaskId)
      .map((task) => '<option value="' + esc(task.id) + '"' + selected(task.id, selectedTaskId) + ">" + esc(displayTaskTitle(task) || task.title || task.id) + "</option>")
      .join("");
  }

  function taskFormTitle(task) {
    if (!task || !task.id) return "";
    return String(state.locale || "").startsWith("zh") ? displayTaskTitle(task) : task.title || "";
  }

  function taskFormGoal(task) {
    if (!task || !task.id) return "";
    if (!String(state.locale || "").startsWith("zh")) return task.goal || "";
    const key = (task.metadata && task.metadata.template_task_key) || String(task.title || "").toLowerCase();
    const goals = {
      implement: "实现需求。",
      test: "运行验证命令并总结失败原因。",
      fix: "根据失败摘要修复问题。",
      complete: "总结改动并确认满足验收标准。",
      reproduce: "复现缺陷并记录触发条件。",
      patch: "修补缺陷。",
      validate: "运行验证并记录结果。",
      review: "复核改动质量和风险。",
      update_docs: "更新相关文档。",
    };
    return goals[key] || task.goal || "";
  }

  function parentTaskId(taskId) {
    if (!taskId || !state.selected) return "";
    const edge = (state.selected.edges || []).find((item) => item.target_task_id === taskId && item.edge_type !== "failure");
    return edge ? edge.source_task_id : "";
  }

  function failureTaskId(taskId) {
    if (!taskId || !state.selected) return "";
    const edge = (state.selected.edges || []).find((item) => item.source_task_id === taskId && item.edge_type === "failure");
    return edge ? edge.target_task_id : "";
  }

  function nextTaskX(parentId) {
    const parent = findTask(parentId);
    if (parent) return Number(parent.position_x || 0) + 260;
    return ((state.selected && state.selected.tasks) || []).length * 260;
  }

  function nextTaskY(parentId) {
    const parent = findTask(parentId);
    return parent ? Number(parent.position_y || 0) : 0;
  }

  function createdTaskId(workflow, beforeIds) {
    const tasks = (workflow && workflow.tasks) || [];
    const created = tasks.find((task) => !beforeIds.has(task.id));
    return created ? created.id : "";
  }

  function reconcileTaskEdges(workflowId, taskId, parentId, failureId) {
    const selectedEdges = (state.selected && state.selected.edges) || [];
    const parentEdges = selectedEdges.filter((edge) => edge.target_task_id === taskId && edge.edge_type !== "failure");
    const failureEdges = selectedEdges.filter((edge) => edge.source_task_id === taskId && edge.edge_type === "failure");
    const operations = [];

    parentEdges.forEach((edge) => {
      if (!parentId || edge.source_task_id !== parentId) operations.push(() => api("/edges/" + encodeURIComponent(edge.id), { method: "DELETE" }));
    });
    if (parentId && !parentEdges.some((edge) => edge.source_task_id === parentId)) {
      operations.push(() => api("/workflows/" + encodeURIComponent(workflowId) + "/edges", {
        method: "POST",
        body: JSON.stringify({ source_task_id: parentId, target_task_id: taskId, edge_type: "success" }),
      }));
    }

    failureEdges.forEach((edge) => {
      if (!failureId || edge.target_task_id !== failureId) operations.push(() => api("/edges/" + encodeURIComponent(edge.id), { method: "DELETE" }));
    });
    if (failureId && !failureEdges.some((edge) => edge.target_task_id === failureId)) {
      operations.push(() => api("/workflows/" + encodeURIComponent(workflowId) + "/edges", {
        method: "POST",
        body: JSON.stringify({ source_task_id: taskId, target_task_id: failureId, edge_type: "failure" }),
      }));
    }

    return operations.reduce((promise, operation) => promise.then(operation), Promise.resolve());
  }

  function logsView() {
    const t = copy();
    const sessions = state.ptySessions || [];
    const pty = sessions.length
      ? [
          '<div class="hf-pty">',
          sessions.map((session) => '<button class="hf-pty-row" data-pty-id="' + esc(session.id) + '"><strong>' + esc(session.closed ? "closed" : "takeover") + '</strong><span>' + esc(session.id) + "</span></button>").join(""),
          '<form class="hf-pty-input"><input name="text" placeholder="' + esc(t.ptyInput) + '" /><button type="submit">' + esc(t.send) + '</button></form>',
          "</div>",
        ].join("")
      : '<div class="hf-empty">' + esc(t.noPty) + '</div>';
    const controls = runControlButtons();
    const logs = state.logRunId ? controls + '<pre class="hf-logs">' + esc((state.logs || []).map((entry) => entry.log).join("\n\n")) + "</pre>" : '<div class="hf-empty">' + esc(t.selectRun) + '</div>';
    return pty + logs + runDetailsView();
  }

  function approvalsView() {
    const t = copy();
    const approvals = state.approvals || [];
    if (!approvals.length) return '<div class="hf-empty">' + esc(t.noApprovals) + '</div>';
    return '<div class="hf-approvals">' + approvals.slice(0, 6).map((approval) => [
      '<div class="hf-approval">',
      '<strong>' + esc(approval.risk_level || "risk") + " · " + esc(approval.executor_type || "") + "</strong>",
      '<span>' + esc(approval.trigger_reason || approval.command || approval.target_path || approval.id) + "</span>",
      approval.log_excerpt ? '<pre>' + esc(approval.log_excerpt) + "</pre>" : "",
      '<button type="button" data-approval-id="' + esc(approval.id) + '" data-decision="allow_once">' + esc(t.allowOnce) + '</button>',
      '<button type="button" data-approval-id="' + esc(approval.id) + '" data-decision="allow_run">' + esc(t.allowRun) + '</button>',
      '<button type="button" data-approval-id="' + esc(approval.id) + '" data-decision="deny">' + esc(t.deny) + '</button>',
      "</div>",
    ].join("")).join("") + "</div>";
  }

  function runControlButtons() {
    const t = copy();
    if (!state.logRunId || !state.runDetails || isTerminalRun(state.runDetails.status)) return "";
    if (state.runDetails.status === "paused") return '<button class="hf-resume-run" type="button">' + esc(t.resume) + '</button><button class="hf-cancel-run" type="button">' + esc(t.cancel) + '</button>';
    return '<button class="hf-pause-run" type="button">' + esc(t.pause) + '</button><button class="hf-cancel-run" type="button">' + esc(t.cancel) + '</button>';
  }

  function runDetailsView() {
    const t = copy();
    const details = state.runDetails;
    if (!details) return "";
    const validation = (details.validation_results || [])
      .map((item) => '<li><strong>' + esc(String(item.exit_code)) + "</strong> " + esc(item.command) + "</li>")
      .join("");
    const summaries = (details.summaries || [])
      .slice(-4)
      .map((item) => '<li><strong>' + esc(item.kind) + "</strong> " + esc(item.content || "") + "</li>")
      .join("");
    return [
      '<div class="hf-run-detail">',
      '<h4>' + esc(t.validation) + '</h4>',
      validation ? "<ul>" + validation + "</ul>" : '<div class="hf-empty">' + esc(t.selectRun) + '</div>',
      '<h4>' + esc(t.status) + '</h4>',
      summaries ? "<ul>" + summaries + "</ul>" : '<div class="hf-empty">' + esc(t.selectRun) + '</div>',
      "</div>",
    ].join("");
  }

  function bindEvents() {
    root.querySelector(".hf-refresh").addEventListener("click", load);
    const projectForm = root.querySelector(".hf-project-form");
    if (projectForm) projectForm.addEventListener("submit", submitProject);
    const agentTemplateForm = root.querySelector(".hf-agent-template-form");
    if (agentTemplateForm) agentTemplateForm.addEventListener("submit", submitAgentTemplate);
    const bindingFormEl = root.querySelector(".hf-binding-form");
    if (bindingFormEl) bindingFormEl.addEventListener("submit", submitBinding);
    root.querySelectorAll("[data-binding-id]").forEach((button) => {
      button.addEventListener("click", () => deleteBinding(button.getAttribute("data-binding-id")));
    });
    root.querySelectorAll("[data-approval-id]").forEach((button) => {
      button.addEventListener("click", () => decideApproval(button.getAttribute("data-approval-id"), button.getAttribute("data-decision")));
    });
    root.querySelectorAll(".hf-project").forEach((button) => {
      button.addEventListener("click", () => selectProject(button.getAttribute("data-project-id")));
    });
    root.querySelectorAll(".hf-workflow").forEach((button) => {
      button.addEventListener("click", () => selectWorkflow(button.getAttribute("data-id")));
    });
    root.querySelectorAll(".hf-run-row").forEach((button) => {
      button.addEventListener("click", () => loadLogs(button.getAttribute("data-run-id")));
    });
    const draftForm = root.querySelector(".hf-draft");
    if (draftForm) {
      draftForm.addEventListener("submit", (event) => {
        event.preventDefault();
        createDraft(new FormData(draftForm).get("goal"));
      });
    }
    const runButton = root.querySelector(".hf-run");
    if (runButton && !runButton.disabled) runButton.addEventListener("click", () => runWorkflow(state.selected.id));
    const confirmButton = root.querySelector(".hf-confirm");
    if (confirmButton) confirmButton.addEventListener("click", () => confirmWorkflow(state.selected.id));
    const useTemplateButton = root.querySelector(".hf-use-template");
    if (useTemplateButton) useTemplateButton.addEventListener("click", () => cloneWorkflow(state.selected.id));
    const taskFormEl = root.querySelector(".hf-task-form");
    if (taskFormEl) taskFormEl.addEventListener("submit", submitTask);
    const newTaskButton = root.querySelector(".hf-new-task");
    if (newTaskButton) newTaskButton.addEventListener("click", () => {
      state.editingTaskId = "";
      render();
    });
    const ptyInput = root.querySelector(".hf-pty-input");
    if (ptyInput) ptyInput.addEventListener("submit", submitPtyInput);
    const cancelRun = root.querySelector(".hf-cancel-run");
    if (cancelRun) cancelRun.addEventListener("click", () => cancelWorkflowRun(state.logRunId));
    const pauseRun = root.querySelector(".hf-pause-run");
    if (pauseRun) pauseRun.addEventListener("click", () => pauseWorkflowRun(state.logRunId));
    const resumeRun = root.querySelector(".hf-resume-run");
    if (resumeRun) resumeRun.addEventListener("click", () => resumeWorkflowRun(state.logRunId));
    root.querySelectorAll(".hf-pty-row").forEach((button) => {
      button.addEventListener("click", () => selectPty(button.getAttribute("data-pty-id")));
    });
    root.querySelectorAll(".hf-node").forEach((button) => {
      button.addEventListener("pointerdown", startNodeDrag);
    });
  }

  function statusText() {
    const t = copy();
    const daemon = state.status && state.status.daemon;
    const hb = daemon && daemon.heartbeat;
    if (!hb || !hb.status) return t.workerMissing;
    return t.worker + " " + hb.status + " · " + t.active + " " + Number(hb.active_workers || 0) + " · " + t.running + " " + Number(daemon.running_workflow_count || 0);
  }

  function load() {
    return Promise.all([api("/status"), api("/projects"), api("/agent-templates"), api("/runs?limit=20"), api("/pty-sessions"), api("/approvals")])
      .then(([status, projects, templates, runs, ptySessions, approvals]) => {
        state.status = status;
        state.projects = projects.projects || [];
        state.agentTemplates = templates.agent_templates || [];
        state.runs = runs.runs || [];
        state.ptySessions = ptySessions.sessions || [];
        state.approvals = approvals.approvals || [];
        if (!state.selectedProject && state.projects[0]) state.selectedProject = state.projects[0].id;
        return loadProjectBindings().then(loadWorkflows);
      })
      .catch((err) => {
        const t = copy();
        root.innerHTML = '<div class="hf-error">' + esc(t.title) + " " + (String(state.locale || "").startsWith("zh") ? "加载失败：" : "failed to load: ") + esc(err.message) + "</div>";
      });
  }

  function loadWorkflows() {
    return api("/workflows?include_templates=true").then((workflows) => {
      state.workflows = workflows.workflows || [];
      const preferred = visibleWorkflows()[0] || templateWorkflows()[0] || null;
      if (!state.selected && preferred) return selectWorkflow(preferred.id);
      if (state.selected && state.workflows.some((wf) => wf.id === state.selected.id)) return selectWorkflow(state.selected.id);
      state.selected = preferred;
      render();
    });
  }

  function selectProject(projectId) {
    state.selectedProject = projectId;
    state.selected = null;
    return loadProjectBindings().then(loadWorkflows);
  }

  function loadProjectBindings() {
    if (!state.selectedProject) {
      state.bindings = [];
      return Promise.resolve();
    }
    return api("/projects/" + encodeURIComponent(state.selectedProject) + "/agent-bindings").then((data) => {
      state.bindings = data.bindings || [];
    });
  }

  function selectWorkflow(id) {
    return api("/workflows/" + encodeURIComponent(id)).then((wf) => {
      state.selected = wf;
      if (!wf.template_key && (wf.tasks || []).length && !(wf.tasks || []).some((task) => task.id === state.editingTaskId)) {
        state.editingTaskId = wf.tasks[0].id;
      }
      render();
    });
  }

  function confirmWorkflow(id) {
    api("/workflows/" + encodeURIComponent(id) + "/confirm", { method: "POST", body: "{}" })
      .then((workflow) => {
        state.selected = workflow;
        return load();
      })
      .catch((err) => alert("Confirm failed: " + err.message));
  }

  function cloneWorkflow(id) {
    const project = findProject(state.selectedProject);
    api("/workflows/" + encodeURIComponent(id) + "/clone", {
      method: "POST",
      body: JSON.stringify({ project_id: state.selectedProject || null, root_dir: project ? project.root_dir : "" }),
    })
      .then((workflow) => {
        state.selected = workflow;
        return load();
      })
      .catch((err) => alert("Template copy failed: " + err.message));
  }

  function runWorkflow(id) {
    api("/runs", { method: "POST", body: JSON.stringify({ workflow_id: id }) })
      .then((run) => {
        state.logRunId = run.id;
        return load();
      })
      .catch((err) => alert("Run queue failed: " + err.message));
  }

  function loadLogs(runId) {
    state.logRunId = runId;
    Promise.all([api("/runs/" + encodeURIComponent(runId) + "/logs"), api("/runs/" + encodeURIComponent(runId)), api("/pty-sessions?run_id=" + encodeURIComponent(runId))])
      .then(([data, details, ptySessions]) => {
        state.logs = data.logs || [];
        state.runDetails = details;
        state.ptySessions = ptySessions.sessions || [];
        render();
      })
      .catch((err) => alert("Log load failed: " + err.message));
  }

  function cancelWorkflowRun(runId) {
    api("/runs/" + encodeURIComponent(runId) + "/cancel", { method: "POST", body: "{}" })
      .then(() => loadLogs(runId))
      .catch((err) => alert("Cancel failed: " + err.message));
  }

  function pauseWorkflowRun(runId) {
    api("/runs/" + encodeURIComponent(runId) + "/pause", { method: "POST", body: "{}" })
      .then(() => loadLogs(runId))
      .catch((err) => alert("Pause failed: " + err.message));
  }

  function resumeWorkflowRun(runId) {
    api("/runs/" + encodeURIComponent(runId) + "/resume", { method: "POST", body: "{}" })
      .then(() => loadLogs(runId))
      .catch((err) => alert("Resume failed: " + err.message));
  }

  function createDraft(goal) {
    const clean = String(goal || "").trim();
    if (!clean) return;
    const project = findProject(state.selectedProject);
    api("/drafts", { method: "POST", body: JSON.stringify({ goal: clean, project_id: state.selectedProject || null, root_dir: project ? project.root_dir : "" }) })
      .then((workflow) => {
        state.selected = workflow;
        return load();
      })
      .catch((err) => alert("Draft failed: " + err.message));
  }

  function submitProject(event) {
    event.preventDefault();
    const data = formData(event.currentTarget);
    if (!String(data.name || "").trim() || !String(data.root_dir || "").trim()) return;
    api("/projects", { method: "POST", body: JSON.stringify({ name: data.name, root_dir: data.root_dir }) })
      .then((project) => {
        state.selectedProject = project.id;
        return load();
      })
      .catch((err) => alert("Project save failed: " + err.message));
  }

  function submitAgentTemplate(event) {
    event.preventDefault();
    const data = formData(event.currentTarget);
    if (!String(data.name || "").trim()) return;
    const config = {};
    if (String(data.command || "").trim()) config.command = String(data.command).trim();
    api("/agent-templates", { method: "POST", body: JSON.stringify({ name: data.name, type: data.type || "hermes_cli", config }) })
      .then(() => load())
      .catch((err) => alert("Agent template save failed: " + err.message));
  }

  function submitBinding(event) {
    event.preventDefault();
    if (!state.selectedProject) return;
    const data = formData(event.currentTarget);
    if (!data.agent_template_id) return;
    api("/projects/" + encodeURIComponent(state.selectedProject) + "/agent-bindings", {
      method: "POST",
      body: JSON.stringify({ role: data.role || "", agent_template_id: data.agent_template_id }),
    })
      .then((result) => {
        state.bindings = result.bindings || [];
        render();
      })
      .catch((err) => alert("Agent binding save failed: " + err.message));
  }

  function deleteBinding(bindingId) {
    api("/agent-bindings/" + encodeURIComponent(bindingId), { method: "DELETE" })
      .then(() => loadProjectBindings().then(render))
      .catch((err) => alert("Agent binding delete failed: " + err.message));
  }

  function decideApproval(approvalId, decision) {
    api("/approvals/" + encodeURIComponent(approvalId) + "/decision", {
      method: "POST",
      body: JSON.stringify({ decision }),
    })
      .then(() => load())
      .catch((err) => alert("Approval decision failed: " + err.message));
  }

  function submitTask(event) {
    event.preventDefault();
    const data = formData(event.currentTarget);
    const existing = findTask(state.editingTaskId) || {};
    const parentId = String(data.parent_task_id || "");
    const failureId = String(data.failure_task_id || "");
    const executorMode = String(data.executor_mode || "ai_agent");
    delete data.parent_task_id;
    delete data.failure_task_id;
    delete data.executor_mode;
    data.execution_dir = existing.execution_dir || "";
    data.agent_template_id = existing.agent_template_id || null;
    data.validation_commands = existing.validation_commands || [];
    data.status = existing.status || "draft";
    data.position_x = Number(existing.position_x == null ? nextTaskX(parentId) : existing.position_x);
    data.position_y = Number(existing.position_y == null ? nextTaskY(parentId) : existing.position_y);
    data.metadata = { ...(existing.metadata || {}), executor_mode: executorMode };
    const path = state.editingTaskId ? "/tasks/" + encodeURIComponent(state.editingTaskId) : "/workflows/" + encodeURIComponent(state.selected.id) + "/tasks";
    const beforeIds = new Set(((state.selected && state.selected.tasks) || []).map((task) => task.id));
    api(path, { method: state.editingTaskId ? "PATCH" : "POST", body: JSON.stringify(data) })
      .then((workflow) => {
        const taskId = state.editingTaskId || createdTaskId(workflow, beforeIds);
        if (!taskId) return selectWorkflow(state.selected.id);
        state.editingTaskId = taskId;
        return reconcileTaskEdges(state.selected.id, taskId, parentId, failureId).then(() => selectWorkflow(state.selected.id));
      })
      .catch((err) => alert("Task save failed: " + err.message));
  }

  function fillTaskForm(taskId) {
    if (!findTask(taskId)) return;
    state.editingTaskId = taskId;
    render();
  }

  function startNodeDrag(event) {
    event.preventDefault();
    const node = event.currentTarget;
    const taskId = node.getAttribute("data-task-id");
    const task = findTask(taskId);
    const canvas = root.querySelector(".hf-canvas");
    if (!task || !canvas) return;
    const rect = node.getBoundingClientRect();
    drag = {
      node,
      task,
      canvas,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
    node.setPointerCapture && node.setPointerCapture(event.pointerId);
    node.classList.add("hf-dragging");
    window.addEventListener("pointermove", moveNodeDrag);
    window.addEventListener("pointerup", endNodeDrag, { once: true });
  }

  function moveNodeDrag(event) {
    if (!drag) return;
    const rect = drag.canvas.getBoundingClientRect();
    const x = Math.max(0, Math.round(event.clientX - rect.left + drag.canvas.scrollLeft - drag.offsetX));
    const y = Math.max(0, Math.round(event.clientY - rect.top + drag.canvas.scrollTop - drag.offsetY));
    drag.node.style.left = x + "px";
    drag.node.style.top = y + "px";
    drag.nextX = x;
    drag.nextY = y;
    drag.moved = drag.moved || Math.abs(event.clientX - drag.startX) > 3 || Math.abs(event.clientY - drag.startY) > 3;
  }

  function endNodeDrag() {
    if (!drag) return;
    window.removeEventListener("pointermove", moveNodeDrag);
    drag.node.classList.remove("hf-dragging");
    drag.node.__hfDragged = drag.moved;
    const done = drag;
    drag = null;
    if (!done.moved) {
      fillTaskForm(done.task.id);
      return;
    }
    updateTaskPosition(done.task, Number(done.nextX || 0), Number(done.nextY || 0));
  }

  function updateTaskPosition(task, x, y) {
    const body = {
      title: task.title || "",
      goal: task.goal || "",
      acceptance_criteria: task.acceptance_criteria || "",
      execution_dir: task.execution_dir || "",
      agent_template_id: task.agent_template_id || null,
      validation_commands: task.validation_commands || [],
      status: task.status || "draft",
      position_x: x,
      position_y: y,
      metadata: { ...(task.metadata || {}), manual_position: true },
    };
    task.position_x = x;
    task.position_y = y;
    api("/tasks/" + encodeURIComponent(task.id), {
      method: "PATCH",
      body: JSON.stringify(body),
    })
      .then(() => selectWorkflow(state.selected.id))
      .catch((err) => {
        alert("Task position save failed: " + err.message);
        load();
      });
  }

  function findTask(taskId) {
    return ((state.selected && state.selected.tasks) || []).find((item) => item.id === taskId);
  }

  function findEdge(edgeId) {
    return ((state.selected && state.selected.edges) || []).find((item) => item.id === edgeId);
  }

  function findProject(projectId) {
    return (state.projects || []).find((item) => item.id === projectId);
  }

  function templateWorkflows() {
    return (state.workflows || []).filter((wf) => wf.template_key);
  }

  function visibleWorkflows() {
    return (state.workflows || []).filter((wf) => !wf.template_key && (!state.selectedProject || wf.project_id === state.selectedProject));
  }

  function displayWorkflowName(wf) {
    if (!wf) return "";
    const key = workflowDisplayKey(wf);
    if (!String(state.locale || "").startsWith("zh") && !wf.template_key) return wf.name || wf.id;
    const map = {
      feature_until_green: state.locale && state.locale.startsWith("zh") ? "功能开发直到验证通过" : "Feature until green",
      bugfix_loop: state.locale && state.locale.startsWith("zh") ? "缺陷修复闭环" : "Bugfix loop",
      refactor_with_guardrails: state.locale && state.locale.startsWith("zh") ? "带护栏的重构" : "Refactor with guardrails",
      docs_validation: state.locale && state.locale.startsWith("zh") ? "文档验证流程" : "Docs validation",
    };
    return map[key] || wf.name || key || wf.id;
  }

  function workflowMeta(wf) {
    const t = copy();
    if (wf.template_key) return t.selectedTemplate;
    return displayStatus(wf.status || "draft") + " · " + (wf.tasks || []).length + " " + t.tasks;
  }

  function displayWorkflowGoal(wf) {
    if (!wf || !String(state.locale || "").startsWith("zh")) return (wf && wf.goal) || "";
    const key = workflowDisplayKey(wf);
    const goals = {
      feature_until_green: "实现需求、运行验证、修复失败，并只在验证通过后完成。",
      bugfix_loop: "复现缺陷、完成修复、运行回归验证，并循环修复直到通过。",
      refactor_with_guardrails: "分析影响、执行重构、运行验证，必要时复核并修复失败。",
      docs_validation: "更新文档，验证命令或链接，必要时复核后完成。",
    };
    return goals[key] || wf.goal || "";
  }

  function workflowDisplayKey(wf) {
    if (!wf) return "";
    if (wf.template_key) return wf.template_key;
    const normalized = String(wf.name || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    const aliases = {
      feature_until_green: "feature_until_green",
      bugfix_loop: "bugfix_loop",
      refactor_with_guardrails: "refactor_with_guardrails",
      docs_validation: "docs_validation",
      docs_validation_: "docs_validation",
      docs: "docs_validation",
    };
    return aliases[normalized] || "";
  }

  function displayTaskTitle(task) {
    if (!task || !String(state.locale || "").startsWith("zh")) return (task && task.title) || "";
    const key = (task.metadata && task.metadata.template_task_key) || String(task.title || "").toLowerCase();
    const titles = {
      implement: "实现",
      test: "测试",
      fix: "修复",
      complete: "完成",
      reproduce: "复现",
      patch: "修补",
      validate: "验证",
      review: "复核",
      document: "文档",
      update_docs: "更新文档",
    };
    return titles[key] || task.title || "";
  }

  function displayStatus(status) {
    if (!String(state.locale || "").startsWith("zh")) return status || "";
    const statuses = {
      template: "模板",
      draft: "草稿",
      confirmed: "已确认",
      ready: "就绪",
      pending: "排队中",
      running: "运行中",
      paused: "已暂停",
      passed: "已通过",
      failed: "失败",
      cancelled: "已取消",
      interrupted: "已中断",
      waiting_input: "等待输入",
      completed: "已完成",
    };
    return statuses[status] || status || "";
  }

  function displayEdgeType(type) {
    if (!String(state.locale || "").startsWith("zh")) return type || "";
    const types = {
      dependency: "依赖",
      success: "成功",
      failure: "失败",
      always: "总是",
      manual: "手动",
    };
    return types[type] || type || "";
  }

  function isTerminalRun(status) {
    return ["passed", "failed", "guardrail_stopped", "cancelled", "interrupted", "stopped"].indexOf(status) !== -1;
  }

  function selected(value, current) {
    return String(value) === String(current || "") ? " selected" : "";
  }

  function selectPty(sessionId) {
    api("/pty-sessions/" + encodeURIComponent(sessionId))
      .then((session) => {
        state.logs = [{ log: session.output || "" }];
        state.logRunId = session.run_id || state.logRunId;
        render();
      })
      .catch((err) => alert("PTY load failed: " + err.message));
  }

  function submitPtyInput(event) {
    event.preventDefault();
    const sessions = state.ptySessions || [];
    const active = sessions.find((session) => !session.closed) || sessions[0];
    if (!active) return;
    const text = new FormData(event.currentTarget).get("text") || "";
    api("/pty-sessions/" + encodeURIComponent(active.id) + "/input", {
      method: "POST",
      body: JSON.stringify({ text: String(text) + "\n" }),
    })
      .then(() => selectPty(active.id))
      .catch((err) => alert("PTY input failed: " + err.message));
  }

  function formData(form) {
    const out = {};
    new FormData(form).forEach((value, key) => {
      out[key] = value;
    });
    return out;
  }

  function splitList(value) {
    return String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function FlowPage() {
    const React = window.__HERMES_PLUGIN_SDK__.React;
    const useI18n = window.__HERMES_PLUGIN_SDK__.useI18n;
    const i18n = useI18n ? useI18n() : { locale: window.localStorage && window.localStorage.getItem("hermes-locale") };
    const locale = (i18n && i18n.locale) || "en";
    const hostRef = React.useRef(null);
    React.useEffect(function () {
      state.locale = locale;
      const host = hostRef.current;
      if (!host) return undefined;
      host.appendChild(root);
      load();
      openEvents();
      pollTimer = setInterval(load, 15000);
      return function () {
        if (pollTimer) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
        if (ws) {
          ws.close();
          ws = null;
        }
        root.remove();
      };
    }, [locale]);
    return React.createElement("div", { className: "hf-plugin-host", ref: hostRef });
  }

  if (
    window.__HERMES_PLUGINS__ &&
    typeof window.__HERMES_PLUGINS__.register === "function" &&
    window.__HERMES_PLUGIN_SDK__ &&
    window.__HERMES_PLUGIN_SDK__.React
  ) {
    window.__HERMES_PLUGINS__.register("hermes-flow", FlowPage);
  }

  function openEvents() {
    const token = window.__HERMES_SESSION_TOKEN__ || "";
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    try {
      ws = new WebSocket(proto + "//" + window.location.host + "/api/plugins/hermes-flow/events?token=" + encodeURIComponent(token));
    } catch (_err) {
      return;
    }
    ws.onmessage = function (event) {
      try {
        const msg = JSON.parse(event.data);
        if (!msg || msg.type !== "flow.snapshot") return;
        state.status = { daemon: msg.data.daemon };
        state.runs = msg.data.runs || state.runs;
        if (state.logRunId && msg.data.log_tails && msg.data.log_tails[state.logRunId]) {
          state.logs = msg.data.log_tails[state.logRunId];
        }
        render();
      } catch (_err) {
        return;
      }
    };
    ws.onclose = function () {
      ws = null;
    };
  }
})();
