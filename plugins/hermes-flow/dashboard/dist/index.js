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
  };

  function api(path, options) {
    return fetch("/api/plugins/hermes-flow" + path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...(options || {}),
    }).then((res) => {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  function render() {
    const workflows = state.workflows || [];
    root.innerHTML = [
      '<section class="hf-shell">',
      '<header class="hf-header">',
      '<div><h1>Hermes Flow</h1><p>Design, queue, observe, and improve software workflow runs.</p></div>',
      '<div class="hf-actions"><span class="hf-status">' + statusText() + '</span><button class="hf-refresh" type="button">Refresh</button></div>',
      "</header>",
      '<div class="hf-grid">',
      '<aside class="hf-list">',
      '<h2>Projects</h2>',
      '<form class="hf-project-form"><input name="name" placeholder="Project name" /><input name="root_dir" placeholder="Root directory" /><button type="submit">Create</button></form>',
      projectList(),
      '<h2>Agent Templates</h2>',
      '<form class="hf-agent-template-form"><input name="name" placeholder="Template name" /><select name="type"><option>hermes_cli</option><option>acp</option><option>pty_cli</option></select><input name="command" placeholder="Command or hermes profile" /><button type="submit">Save</button></form>',
      agentTemplateList(),
      '<h2>Agent Bindings</h2>',
      bindingForm(),
      bindingList(),
      '<h2>Workflows</h2>',
      '<form class="hf-draft"><input name="goal" placeholder="Draft development goal" /><button type="submit">Draft</button></form>',
      workflows.map(workflowButton).join(""),
      '<h2>Runs</h2>',
      (state.runs || []).slice(0, 8).map(runRow).join("") || '<div class="hf-empty">No runs yet.</div>',
      "</aside>",
      '<main class="hf-main">',
      state.selected ? workflowView(state.selected) : '<div class="hf-empty">Select a workflow.</div>',
      "</main>",
      "</div>",
      "</section>",
    ].join("");
    bindEvents();
  }

  function agentTemplateList() {
    const templates = state.agentTemplates || [];
    if (!templates.length) return '<div class="hf-empty">No agent templates.</div>';
    return '<div class="hf-mini-list">' + templates.map((template) => '<span>' + esc(template.name) + " · " + esc(template.type) + "</span>").join("") + "</div>";
  }

  function bindingForm() {
    const templates = state.agentTemplates || [];
    const options = templates.map((template) => '<option value="' + esc(template.id) + '">' + esc(template.name) + " · " + esc(template.type) + "</option>").join("");
    return [
      '<form class="hf-binding-form">',
      '<input name="role" placeholder="Role, e.g. implementer" />',
      '<select name="agent_template_id">' + options + "</select>",
      '<button type="submit"' + (!templates.length || !state.selectedProject ? " disabled" : "") + ">Bind</button>",
      "</form>",
    ].join("");
  }

  function bindingList() {
    const bindings = state.bindings || [];
    if (!state.selectedProject) return '<div class="hf-empty">Select a project.</div>';
    if (!bindings.length) return '<div class="hf-empty">No bindings for this project.</div>';
    return '<div class="hf-mini-list">' + bindings.map((binding) => '<button type="button" data-binding-id="' + esc(binding.id) + '">' + esc(binding.role || "default") + " · " + esc(binding.agent_template_name || binding.agent_template_id) + "</button>").join("") + "</div>";
  }

  function workflowButton(wf) {
    const selected = state.selected && state.selected.id === wf.id ? " hf-active" : "";
    return '<button class="hf-workflow' + selected + '" data-id="' + esc(wf.id) + '"><strong>' + esc(wf.name) + '</strong><span>' + esc(wf.status || "confirmed") + " · " + esc(wf.template_key || wf.id) + '</span></button>';
  }

  function projectList() {
    const projects = state.projects || [];
    if (!projects.length) return '<div class="hf-empty">Create or select a project to start.</div>';
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

  function workflowView(wf) {
    const tasks = wf.tasks || [];
    const edges = wf.edges || [];
    const nodes = tasks.map(nodeView).join("");
    return [
      '<div class="hf-toolbar">',
      '<div><h2>' + esc(wf.name) + '</h2><p>' + esc(wf.goal || "") + '</p><span class="hf-pill">' + esc(wf.status || "confirmed") + "</span></div>",
      workflowActions(wf),
      "</div>",
      '<div class="hf-workspace">',
      '<div class="hf-canvas">' + nodes + "</div>",
      '<aside class="hf-editor">',
      '<h3>Task</h3>',
      taskForm(wf),
      '<h3>Edge</h3>',
      edgeForm(tasks),
      '<h3>Run Logs</h3>',
      logsView(),
      '<h3>Approvals</h3>',
      approvalsView(),
      "</aside>",
      "</div>",
      '<div class="hf-detail">',
      '<strong>' + tasks.length + "</strong> tasks · <strong>" + edges.length + "</strong> edges · guardrails " + esc(String(wf.max_loop_iterations)) + "/" + esc(String(wf.max_task_steps)) + "/" + esc(String(wf.max_duration_minutes)) + "m",
      edgeList(edges, tasks),
      "</div>",
    ].join("");
  }

  function workflowActions(wf) {
    if (wf.template_key) return '<button class="hf-use-template" type="button">Use Template</button>';
    if ((wf.status || "confirmed") !== "confirmed") return '<button class="hf-confirm" type="button">Confirm</button>';
    return '<button class="hf-run" type="button">Queue Run</button>';
  }

  function nodeView(task) {
    return [
      '<button class="hf-node" data-task-id="' + esc(task.id) + '" style="left:' + Number(task.position_x || 0) + 'px;top:' + Number(task.position_y || 0) + 'px">',
      '<strong>' + esc(task.title) + "</strong>",
      '<span>' + esc(task.status) + "</span>",
      "</button>",
    ].join("");
  }

  function taskForm(wf) {
    const task = findTask(state.editingTaskId) || {};
    return [
      '<form class="hf-task-form">',
      '<input name="title" placeholder="Task title" required value="' + esc(task.title || "") + '" />',
      '<textarea name="goal" placeholder="Task goal">' + esc(task.goal || "") + "</textarea>",
      '<textarea name="acceptance_criteria" placeholder="Acceptance criteria">' + esc(task.acceptance_criteria || "") + "</textarea>",
      '<input name="execution_dir" placeholder="Execution dir, relative to root" value="' + esc(task.execution_dir || "") + '" />',
      '<input name="validation_commands" placeholder="Validation commands, comma-separated" value="' + esc((task.validation_commands || []).join(", ")) + '" />',
      '<label class="hf-check"><input name="ai_review_enabled" type="checkbox"' + (((task.metadata || {}).ai_review_enabled) ? " checked" : "") + " /> AI review</label>",
      '<div class="hf-two"><input name="position_x" type="number" placeholder="X" value="' + Number(task.position_x == null ? (wf.tasks || []).length * 240 : task.position_x) + '" /><input name="position_y" type="number" placeholder="Y" value="' + Number(task.position_y || 0) + '" /></div>',
      '<button type="submit">' + (state.editingTaskId ? "Save Task" : "Add Task") + "</button>",
      "</form>",
    ].join("");
  }

  function edgeForm(tasks) {
    const edge = findEdge(state.editingEdgeId) || {};
    const sourceOptions = tasks.map((task) => '<option value="' + esc(task.id) + '"' + selected(task.id, edge.source_task_id) + ">" + esc(task.title) + "</option>").join("");
    const targetOptions = tasks.map((task) => '<option value="' + esc(task.id) + '"' + selected(task.id, edge.target_task_id) + ">" + esc(task.title) + "</option>").join("");
    const edgeType = edge.edge_type || "dependency";
    return [
      '<form class="hf-edge-form">',
      '<select name="source_task_id">' + sourceOptions + "</select>",
      '<select name="target_task_id">' + targetOptions + "</select>",
      '<select name="edge_type">' + ["dependency", "success", "failure", "always", "manual"].map((type) => '<option value="' + type + '"' + selected(type, edgeType) + ">" + type + "</option>").join("") + "</select>",
      '<button type="submit">' + (state.editingEdgeId ? "Save Edge" : "Add Edge") + "</button>",
      "</form>",
    ].join("");
  }

  function edgeList(edges, tasks) {
    const names = {};
    tasks.forEach((task) => {
      names[task.id] = task.title;
    });
    if (!edges.length) return '<div class="hf-edge-list">No edges.</div>';
    return '<div class="hf-edge-list">' + edges.map((edge) => '<button type="button" data-edge-id="' + esc(edge.id) + '">' + esc(names[edge.source_task_id] || edge.source_task_id) + ' -> ' + esc(names[edge.target_task_id] || edge.target_task_id) + ' · ' + esc(edge.edge_type) + "</button>").join("") + "</div>";
  }

  function logsView() {
    const sessions = state.ptySessions || [];
    const pty = sessions.length
      ? [
          '<div class="hf-pty">',
          sessions.map((session) => '<button class="hf-pty-row" data-pty-id="' + esc(session.id) + '"><strong>' + esc(session.closed ? "closed" : "takeover") + '</strong><span>' + esc(session.id) + "</span></button>").join(""),
          '<form class="hf-pty-input"><input name="text" placeholder="Input to selected PTY" /><button type="submit">Send</button></form>',
          "</div>",
        ].join("")
      : '<div class="hf-empty">No PTY takeover sessions.</div>';
    const controls = runControlButtons();
    const logs = state.logRunId ? controls + '<pre class="hf-logs">' + esc((state.logs || []).map((entry) => entry.log).join("\n\n")) + "</pre>" : '<div class="hf-empty">Select a run.</div>';
    return pty + logs + runDetailsView();
  }

  function approvalsView() {
    const approvals = state.approvals || [];
    if (!approvals.length) return '<div class="hf-empty">No approvals.</div>';
    return '<div class="hf-approvals">' + approvals.slice(0, 6).map((approval) => [
      '<div class="hf-approval">',
      '<strong>' + esc(approval.risk_level || "risk") + " · " + esc(approval.executor_type || "") + "</strong>",
      '<span>' + esc(approval.trigger_reason || approval.command || approval.target_path || approval.id) + "</span>",
      approval.log_excerpt ? '<pre>' + esc(approval.log_excerpt) + "</pre>" : "",
      '<button type="button" data-approval-id="' + esc(approval.id) + '" data-decision="allow_once">Allow once</button>',
      '<button type="button" data-approval-id="' + esc(approval.id) + '" data-decision="allow_run">Allow run</button>',
      '<button type="button" data-approval-id="' + esc(approval.id) + '" data-decision="deny">Deny</button>',
      "</div>",
    ].join("")).join("") + "</div>";
  }

  function runControlButtons() {
    if (!state.logRunId || !state.runDetails || isTerminalRun(state.runDetails.status)) return "";
    if (state.runDetails.status === "paused") return '<button class="hf-resume-run" type="button">Resume Run</button><button class="hf-cancel-run" type="button">Cancel Run</button>';
    return '<button class="hf-pause-run" type="button">Pause Run</button><button class="hf-cancel-run" type="button">Cancel Run</button>';
  }

  function runDetailsView() {
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
      '<h4>Validation</h4>',
      validation ? "<ul>" + validation + "</ul>" : '<div class="hf-empty">No validation results.</div>',
      '<h4>Analysis</h4>',
      summaries ? "<ul>" + summaries + "</ul>" : '<div class="hf-empty">No summaries yet.</div>',
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
    const edgeFormEl = root.querySelector(".hf-edge-form");
    if (edgeFormEl) edgeFormEl.addEventListener("submit", submitEdge);
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
      button.addEventListener("click", () => {
        if (button.__hfDragged) {
          button.__hfDragged = false;
          return;
        }
        fillTaskForm(button.getAttribute("data-task-id"));
      });
    });
    root.querySelectorAll(".hf-edge-list button").forEach((button) => {
      button.addEventListener("click", () => fillEdgeForm(button.getAttribute("data-edge-id")));
    });
  }

  function statusText() {
    const daemon = state.status && state.status.daemon;
    const hb = daemon && daemon.heartbeat;
    if (!hb || !hb.status) return "Worker not seen · run: hermes flow daemon";
    return "Worker " + hb.status + " · active " + Number(hb.active_workers || 0) + " · running " + Number(daemon.running_workflow_count || 0);
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
        root.innerHTML = '<div class="hf-error">Hermes Flow failed to load: ' + esc(err.message) + "</div>";
      });
  }

  function loadWorkflows() {
    const query = state.selectedProject ? "?include_templates=true&project_id=" + encodeURIComponent(state.selectedProject) : "?include_templates=true";
    return api("/workflows" + query).then((workflows) => {
      state.workflows = workflows.workflows || [];
      if (!state.selected && state.workflows[0]) return selectWorkflow(state.workflows[0].id);
      if (state.selected && state.workflows.some((wf) => wf.id === state.selected.id)) return selectWorkflow(state.selected.id);
      state.selected = state.workflows[0] || null;
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
    data.validation_commands = splitList(data.validation_commands);
    data.position_x = Number(data.position_x || 0);
    data.position_y = Number(data.position_y || 0);
    const existing = findTask(state.editingTaskId) || {};
    data.metadata = { ...(existing.metadata || {}), ai_review_enabled: data.ai_review_enabled === "on" };
    delete data.ai_review_enabled;
    const path = state.editingTaskId ? "/tasks/" + encodeURIComponent(state.editingTaskId) : "/workflows/" + encodeURIComponent(state.selected.id) + "/tasks";
    api(path, { method: state.editingTaskId ? "PATCH" : "POST", body: JSON.stringify(data) })
      .then((workflow) => {
        state.editingTaskId = "";
        return workflow && workflow.tasks ? ((state.selected = workflow), load()) : selectWorkflow(state.selected.id);
      })
      .catch((err) => alert("Task save failed: " + err.message));
  }

  function submitEdge(event) {
    event.preventDefault();
    const data = formData(event.currentTarget);
    if (!data.source_task_id || !data.target_task_id) return;
    const path = state.editingEdgeId ? "/edges/" + encodeURIComponent(state.editingEdgeId) : "/workflows/" + encodeURIComponent(state.selected.id) + "/edges";
    api(path, { method: state.editingEdgeId ? "PATCH" : "POST", body: JSON.stringify(data) })
      .then((result) => {
        state.editingEdgeId = "";
        return result && result.workflow ? ((state.selected = result.workflow), load()) : selectWorkflow(state.selected.id);
      })
      .catch((err) => alert("Edge save failed: " + err.message));
  }

  function fillTaskForm(taskId) {
    if (!findTask(taskId)) return;
    state.editingTaskId = taskId;
    render();
  }

  function fillEdgeForm(edgeId) {
    if (!findEdge(edgeId)) return;
    state.editingEdgeId = edgeId;
    render();
  }

  function startNodeDrag(event) {
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
    if (!done.moved) return;
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
      metadata: task.metadata || {},
    };
    task.position_x = x;
    task.position_y = y;
    api("/tasks/" + encodeURIComponent(task.id), {
      method: "PATCH",
      body: JSON.stringify(body),
    }).catch((err) => {
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

  window.registerHermesPlugin &&
    window.registerHermesPlugin("hermes-flow", {
      mount: function (el) {
        el.appendChild(root);
        load();
        openEvents();
        pollTimer = setInterval(load, 15000);
      },
      unmount: function () {
        if (pollTimer) clearInterval(pollTimer);
        if (ws) ws.close();
        root.remove();
      },
    });

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
