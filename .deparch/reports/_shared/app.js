const report = JSON.parse(document.getElementById('report-data').textContent);
const graphSvg = document.getElementById('dependency-graph');
const importSvg = document.getElementById('import-graph');
const nodeDetails = document.getElementById('node-details');
const searchInput = document.getElementById('dependency-search');
const depthSelect = document.getElementById('graph-expand-depth');
const backButton = document.getElementById('graph-back');
const resetButton = document.getElementById('graph-reset');
const showAllButton = document.getElementById('graph-show-all');
const visibleSummary = document.getElementById('graph-visible-summary');
const rawData = document.getElementById('raw-data-content');
const sectionButtons = [...document.querySelectorAll('[data-section-target]')];
const sections = [...document.querySelectorAll('.report-section')];

const graphState = {
  mode: 'overview',
  focus: null,
  depth: 0,
  search: '',
  nodes: report.graph_nodes || [],
  edges: report.graph_edges || [],
};
const graphHistory = [];

if (rawData) {
  rawData.textContent = JSON.stringify(report, null, 2);
}

function initSectionNavigation() {
  const initialTarget = window.location.hash?.replace('#', '') || 'summary';

  function activateSection(target) {
    const resolvedTarget = sections.some(section => section.id === target) ? target : 'summary';
    sections.forEach(section => {
      section.hidden = section.id !== resolvedTarget;
    });

    sectionButtons.forEach(button => {
      const active = button.dataset.sectionTarget === resolvedTarget;
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.setAttribute('tabindex', active ? '0' : '-1');
    });
  }

  sectionButtons.forEach(button => {
    button.addEventListener('click', () => {
      const target = button.dataset.sectionTarget;
      history.replaceState(null, '', `#${target}`);
      activateSection(target);
    });
  });

  activateSection(initialTarget);
}

function hasImportGraphData() {
  return Boolean(report.extensions?.import_graph?.nodes?.length);
}

function cloneGraphState() {
  return {
    mode: graphState.mode,
    focus: graphState.focus,
    depth: graphState.depth,
    search: graphState.search,
  };
}

function restoreGraphState(snapshot) {
  graphState.mode = snapshot.mode;
  graphState.focus = snapshot.focus;
  graphState.depth = snapshot.depth;
  graphState.search = snapshot.search;
  if (searchInput) searchInput.value = graphState.search;
  if (depthSelect) depthSelect.value = String(graphState.depth);
  filterDependencyLists(graphState.search);
}

function pushGraphHistory() {
  graphHistory.push(cloneGraphState());
  updateGraphBackButton();
}

function restorePreviousGraphState() {
  const previous = graphHistory.pop();
  if (!previous) return;
  restoreGraphState(previous);
  renderProgressiveGraph();
  updateGraphBackButton();
}

function updateGraphBackButton() {
  if (!backButton) return;
  backButton.disabled = graphHistory.length === 0;
}

function getAvailableMaxDepth() {
  if (!depthSelect) return 0;
  return Math.max(...[...depthSelect.options].map(option => Number(option.value || 0)));
}

function buildRelationMaps(edges) {
  const incoming = new Map();
  const outgoing = new Map();
  edges.forEach(edge => {
    if (!incoming.has(edge.target)) incoming.set(edge.target, []);
    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    incoming.get(edge.target).push(edge.source);
    outgoing.get(edge.source).push(edge.target);
  });
  return { incoming, outgoing };
}

function getNodeMap(nodes) {
  return new Map(nodes.map(node => [node.name, node]));
}

function getSeedNodes(nodes) {
  const directNodes = nodes.filter(node => node.is_direct);
  return directNodes.length ? directNodes : nodes.slice(0, 1);
}

function collectVisibleNodeNames(nodes, edges, mode, focus, depth) {
  if (!nodes.length) {
    return [];
  }

  if (mode === 'all') {
    return nodes.map(node => node.name);
  }

  const { incoming, outgoing } = buildRelationMaps(edges);
  const nodeMap = getNodeMap(nodes);
  const seeds = focus ? [focus] : getSeedNodes(nodes).map(node => node.name);
  const limit = Math.max(0, depth);
  const visited = new Map();
  const queue = seeds.filter(Boolean).map(name => ({ name, depth: 0 }));

  queue.forEach(({ name }) => visited.set(name, 0));

  while (queue.length) {
    const current = queue.shift();
    const neighbors = [
      ...(incoming.get(current.name) || []),
      ...(outgoing.get(current.name) || []),
    ];

    if (current.depth >= limit) {
      continue;
    }

    neighbors.forEach(next => {
      if (!nodeMap.has(next)) {
        return;
      }
      const nextDepth = current.depth + 1;
      if (!visited.has(next) || visited.get(next) > nextDepth) {
        visited.set(next, nextDepth);
        queue.push({ name: next, depth: nextDepth });
      }
    });
  }

  return [...visited.keys()];
}

function layoutNodes(nodes, edges) {
  const { outgoing } = buildRelationMaps(edges);
  const depth = new Map();
  const seeds = getSeedNodes(nodes).map(node => node.name);
  const queue = seeds.map(name => ({ name, depth: 0 }));

  seeds.forEach(name => depth.set(name, 0));
  while (queue.length) {
    const current = queue.shift();
    (outgoing.get(current.name) || []).forEach(next => {
      if (!depth.has(next) || depth.get(next) > current.depth + 1) {
        depth.set(next, current.depth + 1);
        queue.push({ name: next, depth: current.depth + 1 });
      }
    });
  }

  nodes.forEach(node => { if (!depth.has(node.name)) depth.set(node.name, 0); });

  const layers = new Map();
  nodes.forEach(node => {
    const level = depth.get(node.name) || 0;
    if (!layers.has(level)) layers.set(level, []);
    layers.get(level).push(node);
  });

  const sortedLevels = [...layers.keys()].sort((a, b) => a - b);
  const width = 1100;
  const height = 700;
  const xStep = sortedLevels.length > 1 ? (width - 160) / (sortedLevels.length - 1) : 0;
  const positions = new Map();

  sortedLevels.forEach((level, levelIndex) => {
    const layerNodes = layers.get(level).sort((a, b) => a.name.localeCompare(b.name));
    const yStep = height / (layerNodes.length + 1);
    layerNodes.forEach((node, index) => {
      positions.set(node.name, { x: 80 + levelIndex * xStep, y: (index + 1) * yStep });
    });
  });

  return positions;
}

function getEdgeKindClass(edge, nodeMap) {
  const sourceNode = nodeMap.get(edge.source);
  return sourceNode?.is_direct ? 'edge-from-direct' : 'edge-transitive';
}

function renderNodeDetails(node, incoming, outgoing) {
  if (!nodeDetails || !node) return;
  const upstream = incoming.get(node.name) || [];
  const downstream = outgoing.get(node.name) || [];
  const title = document.createElement('h3');
  title.textContent = node.name;
  const list = document.createElement('ul');
  list.className = 'details-list';

  function appendDetail(label, value) {
    const item = document.createElement('li');
    const strong = document.createElement('strong');
    const lineBreak = document.createElement('br');
    strong.textContent = label;
    item.appendChild(strong);
    item.appendChild(lineBreak);
    item.appendChild(document.createTextNode(value));
    list.appendChild(item);
  }

  appendDetail('版本', node.version || 'unknown');
  appendDetail('类型', node.is_direct ? '直接依赖' : '传递依赖');
  appendDetail('来源', node.source || 'graph-derived');
  appendDetail('依赖于', downstream.length ? downstream.join(', ') : '无');
  appendDetail('被依赖于', upstream.length ? upstream.join(', ') : '无');

  nodeDetails.replaceChildren(title, list);
}

function updateGraphSummary(visibleNodes, visibleEdges, modeLabel) {
  if (!visibleSummary) return;
  visibleSummary.textContent = `已显示 ${visibleNodes.length}/${graphState.nodes.length} 个节点 · ${visibleEdges.length}/${graphState.edges.length} 条边 · 当前视图：${modeLabel}`;
}

function renderProgressiveGraph() {
  if (!graphSvg) return;

  const { incoming, outgoing } = buildRelationMaps(graphState.edges);
  const nodeMap = getNodeMap(graphState.nodes);
  const visibleNames = collectVisibleNodeNames(
    graphState.nodes,
    graphState.edges,
    graphState.mode,
    graphState.focus,
    graphState.depth,
  );
  const visibleNameSet = new Set(visibleNames);
  const visibleNodes = graphState.nodes.filter(node => visibleNameSet.has(node.name));
  const visibleEdges = graphState.edges.filter(edge => visibleNameSet.has(edge.source) && visibleNameSet.has(edge.target));
  const positions = layoutNodes(visibleNodes.length ? visibleNodes : graphState.nodes.slice(0, 1), visibleEdges);
  const normalizedFilter = graphState.search.trim().toLowerCase();

  graphSvg.innerHTML = '';

  if (!visibleNodes.length) {
    const empty = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    empty.setAttribute('x', '50%');
    empty.setAttribute('y', '50%');
    empty.setAttribute('text-anchor', 'middle');
    empty.setAttribute('fill', '#94a3b8');
    empty.textContent = '暂无图数据';
    graphSvg.appendChild(empty);
    updateGraphSummary([], [], '概览');
    if (nodeDetails) {
      const message = document.createElement('p');
      message.className = 'small';
      message.textContent = '暂无可视化节点。';
      nodeDetails.replaceChildren(message);
    }
    return;
  }

  visibleEdges.forEach(edge => {
    const from = positions.get(edge.source);
    const to = positions.get(edge.target);
    if (!from || !to) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', from.x);
    line.setAttribute('y1', from.y);
    line.setAttribute('x2', to.x);
    line.setAttribute('y2', to.y);
    line.setAttribute('class', 'edge');
    line.classList.add(getEdgeKindClass(edge, nodeMap));
    line.dataset.source = edge.source;
    line.dataset.target = edge.target;
    if (normalizedFilter && !`${edge.source} ${edge.target}`.toLowerCase().includes(normalizedFilter)) {
      line.classList.add('dimmed');
    }
    if (graphState.focus && (edge.source === graphState.focus || edge.target === graphState.focus)) {
      line.classList.add('active');
    }
    graphSvg.appendChild(line);
  });

  visibleNodes.forEach(node => {
    const pos = positions.get(node.name);
    if (!pos) return;
    const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    group.setAttribute('class', `node ${node.is_direct ? 'direct' : 'transitive'}`);
    group.dataset.name = node.name;
    if (graphState.focus === node.name) {
      group.classList.add('active');
    }
    if (normalizedFilter && !`${node.name} ${node.version || ''} ${node.source || ''}`.toLowerCase().includes(normalizedFilter)) {
      group.classList.add('dimmed');
    }

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', pos.x);
    circle.setAttribute('cy', pos.y);
    circle.setAttribute('r', graphState.focus === node.name ? 28 : node.is_direct ? 25 : 21);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', pos.x);
    text.setAttribute('y', pos.y + 42);
    text.setAttribute('text-anchor', 'middle');
    text.textContent = node.name;

    group.appendChild(circle);
    group.appendChild(text);
    group.addEventListener('click', () => {
      pushGraphHistory();
      graphState.mode = 'focus';
      graphState.focus = node.name;
      if (graphState.depth < 1) {
        graphState.depth = 1;
      }
      graphState.depth = Math.min(graphState.depth, getAvailableMaxDepth());
      if (depthSelect) {
        depthSelect.value = String(graphState.depth);
      }
      renderProgressiveGraph();
    });
    graphSvg.appendChild(group);
  });

  const modeLabel = graphState.mode === 'all'
    ? '显示全部'
    : graphState.mode === 'focus'
      ? `聚焦 ${graphState.focus || '节点'} / ${graphState.depth} 层`
      : graphState.depth > 0
        ? `概览展开 ${graphState.depth} 层`
        : '概览';

  updateGraphSummary(visibleNodes, visibleEdges, modeLabel);

  const selectedNode = graphState.focus
    ? nodeMap.get(graphState.focus)
    : visibleNodes[0] || graphState.nodes[0];

  if (selectedNode) {
    renderNodeDetails(selectedNode, incoming, outgoing);
  }
  updateGraphBackButton();
}

function filterDependencyLists(filter) {
  const normalizedFilter = filter.trim().toLowerCase();
  document.querySelectorAll('.dependency-item').forEach(item => {
    const haystack = `${item.dataset.name} ${item.dataset.version} ${item.textContent}`.toLowerCase();
    item.style.display = (!normalizedFilter || haystack.includes(normalizedFilter)) ? '' : 'none';
  });
}

function renderAuxiliaryGraph(svg, nodes, edges, filter = '') {
  if (!svg) return;
  const normalizedFilter = filter.trim().toLowerCase();
  const positions = layoutNodes(nodes, edges);
  const { incoming, outgoing } = buildRelationMaps(edges);
  svg.innerHTML = '';

  edges.forEach(edge => {
    const from = positions.get(edge.source);
    const to = positions.get(edge.target);
    if (!from || !to) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', from.x);
    line.setAttribute('y1', from.y);
    line.setAttribute('x2', to.x);
    line.setAttribute('y2', to.y);
    line.setAttribute('class', 'edge');
    line.classList.add(getEdgeKindClass(edge, getNodeMap(nodes)));
    line.dataset.source = edge.source;
    line.dataset.target = edge.target;
    if (normalizedFilter && !`${edge.source} ${edge.target}`.toLowerCase().includes(normalizedFilter)) {
      line.classList.add('dimmed');
    }
    svg.appendChild(line);
  });

  nodes.forEach(node => {
    const pos = positions.get(node.name);
    if (!pos) return;
    const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    group.setAttribute('class', `node ${node.is_direct ? 'direct' : 'transitive'}`);
    group.dataset.name = node.name;
    if (normalizedFilter && !`${node.name} ${node.version || ''} ${node.source || ''}`.toLowerCase().includes(normalizedFilter)) {
      group.classList.add('dimmed');
    }

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', pos.x);
    circle.setAttribute('cy', pos.y);
    circle.setAttribute('r', node.is_direct ? 26 : 22);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', pos.x);
    text.setAttribute('y', pos.y + 42);
    text.setAttribute('text-anchor', 'middle');
    text.textContent = node.name;

    group.appendChild(circle);
    group.appendChild(text);
    group.addEventListener('click', () => {
      document.querySelectorAll('.node').forEach(item => item.classList.toggle('active', item.dataset.name === node.name));
      document.querySelectorAll('.edge').forEach(edgeEl => {
        const active = edgeEl.dataset.source === node.name || edgeEl.dataset.target === node.name;
        edgeEl.classList.toggle('active', active);
      });
      renderNodeDetails(node, incoming, outgoing);
    });
    svg.appendChild(group);
  });

  if (nodes.length) {
    renderNodeDetails(nodes[0], incoming, outgoing);
  }
}

function renderImportGraphIfAvailable(filter = '') {
  if (!hasImportGraphData()) return;
  renderAuxiliaryGraph(
    importSvg,
    report.extensions.import_graph.nodes || [],
    report.extensions.import_graph.edges || [],
    filter,
  );
}

function init() {
  initSectionNavigation();
  if (searchInput) {
    searchInput.addEventListener('input', event => {
      const value = event.target.value;
      graphState.search = value;
      filterDependencyLists(value);
      renderProgressiveGraph();
      renderImportGraphIfAvailable(value);
    });
  }
  if (depthSelect) {
    depthSelect.addEventListener('change', event => {
      pushGraphHistory();
      graphState.depth = Number(event.target.value || 0);
      if (graphState.mode !== 'all') {
        graphState.mode = graphState.focus ? 'focus' : 'overview';
      }
      if (graphState.mode === 'overview' && graphState.depth > 0) {
        graphState.focus = null;
      }
      renderProgressiveGraph();
    });
  }
  if (backButton) {
    backButton.addEventListener('click', restorePreviousGraphState);
    updateGraphBackButton();
  }
  if (resetButton) {
    resetButton.addEventListener('click', () => {
      pushGraphHistory();
      graphState.mode = 'overview';
      graphState.focus = null;
      graphState.depth = 0;
      if (depthSelect) depthSelect.value = '0';
      renderProgressiveGraph();
    });
  }
  if (showAllButton) {
    showAllButton.addEventListener('click', () => {
      pushGraphHistory();
      graphState.mode = 'all';
      graphState.focus = null;
      renderProgressiveGraph();
    });
  }

  renderProgressiveGraph();
  renderImportGraphIfAvailable();
  filterDependencyLists('');
}

init();
