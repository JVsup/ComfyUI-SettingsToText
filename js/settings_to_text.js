import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Comfy.SettingsToText",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "SettingsToText") {
            const style = document.createElement("style");
            style.textContent = `
                .stt-wrapper { background: #222; border: 1px solid #444; padding: 5px; display: flex; flex-direction: column; gap: 5px; width: 100%; height: 100%; box-sizing: border-box; }
                .stt-container { overflow-y: auto; color: #bbb; font-family: monospace; font-size: 12px; flex: 1; min-height: 50px; }
                .stt-btn-group { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; flex-shrink: 0; }
                .stt-btn { background: #444; color: #fff; border: 1px solid #555; padding: 4px 2px; cursor: pointer; font-size: 10px; text-align: center; border-radius: 3px; transition: background 0.2s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
                .stt-btn:hover { background: #666; }
                .stt-btn:active { background: #333; }
                .stt-node-row { cursor: pointer; padding: 4px 0; user-select: none; border-bottom: 1px solid #333; display: flex; align-items: center; }
                .stt-node-row:hover { background: #333; color: #fff; }
                .stt-node-check { display: inline-block; width: 18px; text-align: center; margin-right: 5px; color: #666; font-weight: bold; border-right: 1px solid #444; }
                .stt-node-check:hover { color: #fff; background: #555; }
                .stt-node-check.checked { color: #4fce4f; }
                .stt-param-row { padding-left: 30px; cursor: pointer; color: #888; display: flex; align-items: center; padding-top: 2px; padding-bottom: 2px; }
                .stt-param-row:hover { color: #ddd; background: #2a2a2a; }
                .stt-param-row.selected { color: #4fce4f; font-weight: bold; background: #1a3a1a; }
                .stt-arrow { display: inline-block; width: 15px; text-align: center; transition: transform 0.1s; color: #666; margin-right: 2px; }
                .stt-expanded .stt-arrow { transform: rotate(90deg); color: #fff; }
                .stt-hidden { display: none; }
                .stt-check { width: 15px; display: inline-block; text-align: center; margin-right: 5px; }
            `;
            document.head.appendChild(style);

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                this.size = [320, 450];
                const wSettingsJson = this.widgets.find(w => w.name === "settings_json");
                if (wSettingsJson) { wSettingsJson.type = "converted-widget"; if (!wSettingsJson.value) wSettingsJson.value = "[]"; }

                const mainWrapper = document.createElement("div"); mainWrapper.className = "stt-wrapper";
                const btnGroup = document.createElement("div"); btnGroup.className = "stt-btn-group";
                const selectAllBtn = document.createElement("button"); selectAllBtn.className = "stt-btn"; selectAllBtn.textContent = "SELECT ALL";
                const resetBtn = document.createElement("button"); resetBtn.className = "stt-btn"; resetBtn.textContent = "RESET";
                const expandAllBtn = document.createElement("button"); expandAllBtn.className = "stt-btn"; expandAllBtn.textContent = "EXPAND ALL";
                const collapseAllBtn = document.createElement("button"); collapseAllBtn.className = "stt-btn"; collapseAllBtn.textContent = "COLLAPSE ALL";
                btnGroup.appendChild(selectAllBtn); btnGroup.appendChild(resetBtn); btnGroup.appendChild(expandAllBtn); btnGroup.appendChild(collapseAllBtn);
                const treeContainer = document.createElement("div"); treeContainer.className = "stt-container";
                mainWrapper.appendChild(btnGroup); mainWrapper.appendChild(treeContainer);
                this.addDOMWidget("tree_view", "div", mainWrapper, { serialize: false, hideOnZoom: false });

                this.onResize = function(size) { if (this.onResize_orig) this.onResize_orig(size); };

                let selectedItems = [];
                let expandedNodeIds = new Set();
                try { if (wSettingsJson && wSettingsJson.value) selectedItems = JSON.parse(wSettingsJson.value); } catch (e) { selectedItems = []; }
                const saveState = () => { wSettingsJson.value = JSON.stringify(selectedItems); app.graph.setDirtyCanvas(true, true); };
                
                const getNodeParams = (node) => {
                    let params = [];
                    if (node.widgets) params = params.concat(node.widgets.map(w => w.name));
                    if (node.inputs) params = params.concat(node.inputs.map(i => i.name));
                    return [...new Set(params)].sort();
                };

                resetBtn.onclick = () => { if (selectedItems.length === 0) return; selectedItems = []; saveState(); renderTree(); };
                selectAllBtn.onclick = () => {
                    const allNodes = app.graph._nodes; if (!allNodes) return;
                    const newSelection = [];
                    for (const node of allNodes) {
                        if (node.id === this.id) continue;
                        if (node.mode === 2 || node.mode === 4) continue;
                        const nodeTitle = node.title || node.type;
                        const params = getNodeParams(node);
                        for (const pName of params) newSelection.push({ id: node.id, param: pName, title: nodeTitle });
                    }
                    selectedItems = newSelection; saveState(); renderTree();
                };
                expandAllBtn.onclick = () => { const allNodes = app.graph._nodes; if (!allNodes) return; for (const node of allNodes) { if (node.id === this.id) continue; if (node.mode === 2 || node.mode === 4) continue; expandedNodeIds.add(node.id); } renderTree(); };
                collapseAllBtn.onclick = () => { expandedNodeIds.clear(); renderTree(); };

                const toggleSelection = (nodeId, paramName, nodeTitle) => {
                    const index = selectedItems.findIndex(i => i.id == nodeId && i.param == paramName);
                    if (index > -1) selectedItems.splice(index, 1); else selectedItems.push({ id: nodeId, param: paramName, title: nodeTitle });
                    saveState(); renderTree();
                };
                const toggleNodeSelection = (nodeId, nodeTitle, allParams) => {
                    const areAllSelected = allParams.every(p => selectedItems.some(item => item.id == nodeId && item.param == p));
                    if (areAllSelected) selectedItems = selectedItems.filter(item => item.id != nodeId);
                    else allParams.forEach(p => { if (!selectedItems.some(item => item.id == nodeId && item.param == p)) selectedItems.push({ id: nodeId, param: p, title: nodeTitle }); });
                    saveState(); renderTree();
                };
                const isSelected = (nodeId, paramName) => { return selectedItems.some(i => i.id == nodeId && i.param == paramName); };

                const renderTree = () => {
                    const scrollTop = treeContainer.scrollTop; treeContainer.innerHTML = "";
                    const allNodes = app.graph._nodes; if (!allNodes) return;
                    const sortedNodes = [...allNodes].sort((a, b) => a.id - b.id);
                    sortedNodes.forEach(node => {
                        if (node.id === this.id) return;
                        if (node.mode === 2 || node.mode === 4) return;
                        const nodeId = node.id; const nodeTitle = node.title || node.type;
                        const isExpanded = expandedNodeIds.has(nodeId); const params = getNodeParams(node);
                        const nodeRow = document.createElement("div"); nodeRow.className = "stt-node-row"; if (isExpanded) nodeRow.classList.add("stt-expanded");
                        const arrow = document.createElement("span"); arrow.className = "stt-arrow"; arrow.textContent = "▶";
                        const nodeCheck = document.createElement("span"); nodeCheck.className = "stt-node-check";
                        const allSelected = params.length > 0 && params.every(p => isSelected(nodeId, p));
                        nodeCheck.textContent = allSelected ? "✓" : "☐"; if (allSelected) nodeCheck.classList.add("checked");
                        nodeCheck.onclick = (e) => { e.stopPropagation(); toggleNodeSelection(nodeId, nodeTitle, params); };
                        const label = document.createElement("span"); label.textContent = `#${nodeId}: ${nodeTitle}`;
                        nodeRow.appendChild(arrow); nodeRow.appendChild(nodeCheck); nodeRow.appendChild(label);
                        const paramsContainer = document.createElement("div"); if (!isExpanded) paramsContainer.classList.add("stt-hidden");
                        if (params.length > 0) {
                            params.forEach(pName => {
                                const pRow = document.createElement("div"); pRow.className = "stt-param-row";
                                const selected = isSelected(nodeId, pName); if (selected) pRow.classList.add("selected");
                                const check = document.createElement("span"); check.className = "stt-check"; check.textContent = selected ? "✓" : "";
                                const pText = document.createElement("span"); pText.textContent = pName;
                                pRow.appendChild(check); pRow.appendChild(pText);
                                pRow.onclick = (e) => { e.stopPropagation(); toggleSelection(nodeId, pName, nodeTitle); };
                                paramsContainer.appendChild(pRow);
                            });
                        } else {
                             const empty = document.createElement("div"); empty.className = "stt-param-row"; empty.style.fontStyle = "italic"; empty.textContent = "(no parameters)"; paramsContainer.appendChild(empty);
                        }
                        nodeRow.onclick = () => { const expandedNow = nodeRow.classList.toggle("stt-expanded"); if (expandedNow) { expandedNodeIds.add(nodeId); paramsContainer.classList.remove("stt-hidden"); } else { expandedNodeIds.delete(nodeId); paramsContainer.classList.add("stt-hidden"); } };
                        treeContainer.appendChild(nodeRow); treeContainer.appendChild(paramsContainer);
                    });
                    treeContainer.scrollTop = scrollTop;
                };
                this.onMouseEnter = function(e) { if (!mainWrapper.matches(':hover')) renderTree(); if (this.onMouseEnter_orig) this.onMouseEnter_orig(e); };
                setTimeout(renderTree, 200); return r;
            };
        }
    },
});