/**
 * DICOM Viewer Web Application
 * 前端 JavaScript 应用
 */

class DicomViewerApp {
    constructor() {
        this.accessToken = localStorage.getItem("accessToken");
        this.currentPath = "";
        this.currentFilePath = null;
        this.frameBlobCache = new Map();
        this.seriesFrameCache = new Map();
        this.seriesLoadPromise = new Map();
        this.maxCachedFrames = 16; // 可配置的前端缓存帧数
        this.currentUser = null;
        this.currentDicomMetadata = null;
        this.remoteCache = {}; // 缓存远端刷新得到的目录结构，key = path
        this.cacheStatusTimer = null;
        this.selectedOCREngine = localStorage.getItem("selectedOCREngine") || "tesseract";
        this.imageState = {
            img: null,
            objectUrl: null,
            naturalWidth: 0,
            naturalHeight: 0,
            fitScale: 1,
            zoom: 1,
            panX: 0,
            panY: 0,
            displayWidth: 0,
            displayHeight: 0,
            dragging: false,
            dragStartX: 0,
            dragStartY: 0,
            dragBasePanX: 0,
            dragBasePanY: 0,
            currentFrame: 0,
            playing: false,
        };
        this.imageDragListenersBound = false;
        this.init();
    }

    async init() {
        if (!this.accessToken) {
            this.showLoginPage();
        } else {
            this.showMainPage();
            await this.loadFileTree();
        }
    }

    // ============ 认证 ============

    showLoginPage() {
        document.body.innerHTML = `
            <div class="login-container">
                <div class="login-form">
                    <h2>DICOM Viewer</h2>
                    <form id="loginForm">
                        <div class="form-group">
                            <label for="username">用户名</label>
                            <input type="text" id="username" required>
                        </div>
                        <div class="form-group">
                            <label for="password">密码</label>
                            <input type="password" id="password" required>
                        </div>
                        <div class="form-group">
                            <button type="submit">登录</button>
                        </div>
                        <div id="loginError" class="login-error"></div>
                    </form>
                </div>
            </div>
        `;

        document.getElementById("loginForm").addEventListener("submit", (e) =>
            this.handleLogin(e)
        );
    }

    async handleLogin(e) {
        e.preventDefault();
        const username = document.getElementById("username").value;
        const password = document.getElementById("password").value;

        try {
            const response = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
            });

            if (response.ok) {
                const data = await response.json();
                this.accessToken = data.access_token;
                localStorage.setItem("accessToken", this.accessToken);
                this.showMainPage();
                await this.loadFileTree();
            } else {
                document.getElementById("loginError").textContent =
                    "登录失败，请检查用户名和密码";
            }
        } catch (error) {
            document.getElementById("loginError").textContent = "登录错误：" + error.message;
        }
    }

    showMainPage() {
        document.body.innerHTML = `
            <div class="container">
                <div class="sidebar">
                    <div class="header">
                        <h1 style="font-size: 16px;">文件浏览</h1>
                        <button id="refreshBtn" class="refresh-btn">刷新</button>
                    </div>
                    <div class="file-tree" id="fileTree"></div>
                </div>
                <div class="main-content">
                    <div class="header">
                        <div class="viewer-title">
                            <h1>DICOM 查看器</h1>
                            <span id="cacheStatus" class="cache-status cache-status-hidden"></span>
                        </div>
                        <div class="user-info">
                            <span id="currentUser"></span>
                            <button class="logout-btn" onclick="app.logout()">登出</button>
                        </div>
                    </div>
                    <div class="breadcrumb" id="breadcrumb"></div>
                    <div class="content-area">
                        <div class="content-panel">
                            <div class="metadata-panel" id="metadataPanel">
                                <div class="loading">
                                    <span>选择文件查看详情</span>
                                </div>
                            </div>
                            <div class="image-panel" id="imagePanel">
                                <div class="image-toolbar">
                                    <button id="zoomOutBtn" class="zoom-btn">-</button>
                                    <button id="zoomResetBtn" class="zoom-btn">适配</button>
                                    <button id="zoomInBtn" class="zoom-btn">+</button>
                                    <button id="analyzeBtn" class="zoom-btn analyze-btn">解析</button>
                                    <select id="analysisModeSelect" class="analysis-mode-select" title="影像提取方式"></select>
                                    <select id="ocrEngineSelect" class="ocr-engine-select" title="OCR 引擎"></select>
                                    <span id="zoomLevel" class="zoom-level">100%</span>
                                    <div class="frame-controls" id="frameControls" style="margin-left:16px; display:inline-flex; align-items:center; gap:8px;">
                                        <button id="framePrevBtn" class="frame-btn">◀</button>
                                        <span id="frameLabel">帧 0/1</span>
                                        <button id="frameNextBtn" class="frame-btn">▶</button>
                                    </div>
                                </div>
                                <div class="analysis-panel analysis-panel-hidden" id="analysisPanel"></div>
                                <div class="image-viewport" id="imageViewport">
                                    <div class="loading">
                                        <span>选择 DICOM 文件查看图像</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        this.loadCurrentUser();
        this.bindImageControls();
        this.loadAnalysisModes();
        this.loadOCREngines();
        this.startCacheStatusPolling();
        document.addEventListener('click', (e) => {
            if (e.target && e.target.id === 'refreshBtn') {
                this.handleRefresh();
            }
        });
    }

    logout() {
        this.stopCacheStatusPolling();
        this.clearImageState();
        localStorage.removeItem("accessToken");
        this.accessToken = null;
        this.showLoginPage();
    }

    async loadCurrentUser() {
        try {
            const response = await this.apiCall("/api/auth/me");
            const user = await response.json();
            this.currentUser = user;
            document.getElementById("currentUser").textContent = `用户: ${user.username}`;
        } catch (error) {
            console.error("Failed to load user:", error);
        }
    }

    startCacheStatusPolling() {
        this.stopCacheStatusPolling();
        this.updateCacheStatus();
        this.cacheStatusTimer = setInterval(() => this.updateCacheStatus(), 3000);
    }

    stopCacheStatusPolling() {
        if (this.cacheStatusTimer) {
            clearInterval(this.cacheStatusTimer);
            this.cacheStatusTimer = null;
        }
    }

    async updateCacheStatus() {
        const badge = document.getElementById("cacheStatus");
        if (!badge) {
            return;
        }

        try {
            const response = await this.apiCall("/api/sync/cache/status");
            const stats = await response.json();

            // 确保清理错误样式
            badge.classList.remove("cache-status-error");
            badge.classList.remove("cache-status-hidden");

            // 在磁盘模式下也显示当前模式/信息，而不是隐藏状态条
            if (stats.fetch_mode === "disk") {
                const modeText = "磁盘模式";
                const maxBytesText = (stats.max_bytes === null || stats.max_bytes === undefined)
                    ? "未知"
                    : this.formatBytes(stats.max_bytes);
                const bytesText = `${this.formatBytes(stats.bytes)} / ${maxBytesText}`;
                const maxItemsText = stats.max_items !== undefined && stats.max_items !== null ? `${stats.items}/${stats.max_items}` : `${stats.items}`;
                badge.textContent = `模式 ${modeText} · 缓存 ${maxItemsText} · ${bytesText}`;
                return;
            }

            const maxBytesText = (stats.max_bytes === null || stats.max_bytes === undefined)
                ? "未知"
                : this.formatBytes(stats.max_bytes);
            const bytesText = `${this.formatBytes(stats.bytes)} / ${maxBytesText}`;
            const modeText = stats.fetch_mode ? ` · ${stats.fetch_mode}` : "";
            const maxItemsText = stats.max_items !== undefined && stats.max_items !== null ? `${stats.items}/${stats.max_items}` : `${stats.items}`;
            badge.textContent = `缓存 ${maxItemsText} · ${bytesText}${modeText}`;
            badge.classList.remove("cache-status-hidden");
        } catch (error) {
            // 当与后端服务连接失败时，状态条显示失联提示，作为全局状态提示
            badge.classList.remove("cache-status-hidden");
            badge.classList.add("cache-status-error");
            badge.textContent = "服务失联 · 无法连接到同步服务";
        }
    }

    formatBytes(bytes) {
        if (bytes === null || bytes === undefined) {
            return "0 B";
        }
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
        return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
    }

    bindImageControls() {
        const zoomInBtn = document.getElementById("zoomInBtn");
        const zoomOutBtn = document.getElementById("zoomOutBtn");
        const zoomResetBtn = document.getElementById("zoomResetBtn");
        const analyzeBtn = document.getElementById("analyzeBtn");
        const analysisModeSelect = document.getElementById("analysisModeSelect");
        const viewport = document.getElementById("imageViewport");

        if (zoomInBtn) zoomInBtn.onclick = () => this.zoomImage(1.15);
        if (zoomOutBtn) zoomOutBtn.onclick = () => this.zoomImage(1 / 1.15);
        if (zoomResetBtn) zoomResetBtn.onclick = () => this.resetImageZoom();
        if (analyzeBtn) analyzeBtn.onclick = () => this.analyzeCurrentImage();
        if (analysisModeSelect) {
            analysisModeSelect.addEventListener("change", () => {
                // 切换提取方式后，不立即触发解析，仅影响下次点击“解析”按钮。
            });
        }

        if (viewport) {
            viewport.style.position = "relative";
            viewport.style.overflow = "hidden";
            viewport.style.userSelect = "none";
            viewport.style.touchAction = "none";
            viewport.addEventListener("wheel", (event) => this.handleFrameWheel(event), { passive: false });
            viewport.addEventListener("mousedown", (event) => this.handleImageMouseDown(event));
        }

        if (!this.imageDragListenersBound) {
            document.addEventListener("mousemove", (event) => this.handleImageMouseMove(event));
            document.addEventListener("mouseup", (event) => this.handleImageMouseUp(event));
            document.addEventListener("mouseleave", () => this.handleImageMouseUp());
            this.imageDragListenersBound = true;
        }

        // 帧控件绑定
        const prevBtn = document.getElementById("framePrevBtn");
        const nextBtn = document.getElementById("frameNextBtn");
        if (prevBtn) prevBtn.addEventListener('click', () => this.prevFrame());
        if (nextBtn) nextBtn.addEventListener('click', () => this.nextFrame());
    }

    async loadAnalysisModes() {
        const select = document.getElementById("analysisModeSelect");
        if (!select) {
            return;
        }

        const fallbackModes = [
            { mode: "opencv_border_relaxed", label: "边缘黑矩形（宽松）" },
            { mode: "opencv_border_strict", label: "边缘黑矩形（严格）" },
        ];

        try {
            const response = await this.apiCall("/api/dicom/analyze/modes");
            if (!response.ok) {
                throw new Error("无法获取解析模式");
            }

            const modes = await response.json();
            const options = Array.isArray(modes) && modes.length ? modes : fallbackModes;
            select.innerHTML = options.map((item) => `<option value="${this.escapeHtml(item.mode)}">${this.escapeHtml(item.label || item.mode)}</option>`).join("");
        } catch (error) {
            select.innerHTML = fallbackModes.map((item) => `<option value="${this.escapeHtml(item.mode)}">${this.escapeHtml(item.label)}</option>`).join("");
        }
    }

    async loadOCREngines() {
        const select = document.getElementById("ocrEngineSelect");
        if (!select) return;

        const fallback = [
            { mode: "tesseract", label: "Tesseract" }
        ];

        try {
            const resp = await this.apiCall('/api/dicom/analyze/engines');
            if (!resp.ok) throw new Error('无法获取 OCR 引擎列表');
            const list = await resp.json();
            const options = Array.isArray(list) && list.length ? list : fallback;
            select.innerHTML = options.map((item) => `<option value="${this.escapeHtml(item.mode)}">${this.escapeHtml(item.label || item.mode)}</option>`).join("");
            const preferred = this.selectedOCREngine || "tesseract";
            select.value = options.some((item) => item.mode === preferred) ? preferred : options[0].mode;
            this.selectedOCREngine = select.value;
            localStorage.setItem("selectedOCREngine", this.selectedOCREngine);
            select.addEventListener("change", () => {
                this.selectedOCREngine = select.value;
                localStorage.setItem("selectedOCREngine", this.selectedOCREngine);
            });
        } catch (err) {
            select.innerHTML = fallback.map((item) => `<option value="${this.escapeHtml(item.mode)}">${this.escapeHtml(item.label)}</option>`).join("");
            select.value = this.selectedOCREngine || "tesseract";
        }
    }

    handleFrameWheel(event) {
        // 如果按下 Ctrl (或 macOS 的 Meta)，优先执行缩放
        if (event.ctrlKey || event.metaKey) {
            event.preventDefault();
            event.stopPropagation();
            const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
            this.zoomImage(factor);
            return;
        }

        if (!this.currentFilePath || !this.currentDicomMetadata) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();

        const total = (this.currentDicomMetadata && this.currentDicomMetadata.number_of_frames) ? this.currentDicomMetadata.number_of_frames : 1;
        if (total <= 1) {
            return;
        }

        const direction = event.deltaY > 0 ? 1 : -1;
        const nextFrame = Math.max(0, Math.min(total - 1, (this.imageState.currentFrame || 0) + direction));
        if (nextFrame !== this.imageState.currentFrame) {
            this.setFrame(nextFrame);
        }
    }

    handleImageMouseDown(event) {
        if (event.button !== 0) {
            return;
        }

        if (!this.canPanImage()) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();

        this.imageState.dragging = true;
        this.imageState.dragStartX = event.clientX;
        this.imageState.dragStartY = event.clientY;
        this.imageState.dragBasePanX = this.imageState.panX || 0;
        this.imageState.dragBasePanY = this.imageState.panY || 0;

        const viewport = document.getElementById("imageViewport");
        if (viewport) {
            viewport.style.cursor = "grabbing";
        }
        document.body.style.userSelect = "none";
    }

    handleImageMouseMove(event) {
        if (!this.imageState.dragging) {
            return;
        }

        event.preventDefault();

        const deltaX = event.clientX - this.imageState.dragStartX;
        const deltaY = event.clientY - this.imageState.dragStartY;
        this.imageState.panX = this.imageState.dragBasePanX + deltaX;
        this.imageState.panY = this.imageState.dragBasePanY + deltaY;
        this.clampPanToViewport();
        this.renderCurrentImage();
    }

    handleImageMouseUp() {
        if (!this.imageState.dragging) {
            return;
        }

        this.imageState.dragging = false;
        const viewport = document.getElementById("imageViewport");
        if (viewport) {
            viewport.style.cursor = this.canPanImage() ? "grab" : "default";
        }
        document.body.style.userSelect = "";
    }

    canPanImage() {
        if (!this.imageState.img) {
            return false;
        }

        const viewport = document.getElementById("imageViewport");
        if (!viewport) {
            return false;
        }

        const availableWidth = Math.max(1, viewport.clientWidth - 32);
        const availableHeight = Math.max(1, viewport.clientHeight - 32);
        return (this.imageState.displayWidth || 0) > availableWidth || (this.imageState.displayHeight || 0) > availableHeight;
    }

    clampPanToViewport() {
        const viewport = document.getElementById("imageViewport");
        if (!viewport || !this.imageState.img) {
            return;
        }

        const availableWidth = Math.max(1, viewport.clientWidth - 32);
        const availableHeight = Math.max(1, viewport.clientHeight - 32);
        const overflowX = Math.max(0, ((this.imageState.displayWidth || 0) - availableWidth) / 2);
        const overflowY = Math.max(0, ((this.imageState.displayHeight || 0) - availableHeight) / 2);

        if (overflowX > 0) {
            this.imageState.panX = Math.max(-overflowX, Math.min(overflowX, this.imageState.panX || 0));
        } else {
            this.imageState.panX = 0;
        }

        if (overflowY > 0) {
            this.imageState.panY = Math.max(-overflowY, Math.min(overflowY, this.imageState.panY || 0));
        } else {
            this.imageState.panY = 0;
        }
    }

    zoomImage(factor) {
        if (!this.imageState.img) {
            return;
        }

        const nextZoom = Math.min(8, Math.max(0.1, this.imageState.zoom * factor));
        this.imageState.zoom = nextZoom;
        this.renderCurrentImage();
    }

    resetImageZoom() {
        if (!this.imageState.img) {
            return;
        }

        this.imageState.zoom = 1;
        this.renderCurrentImage();
    }

    clearImageState(preserveZoom = false) {
        const prevZoom = (this.imageState && this.imageState.zoom) ? this.imageState.zoom : 1;
        if (this.imageState && this.imageState.objectUrl && String(this.imageState.objectUrl).startsWith('blob:')) {
            try { URL.revokeObjectURL(this.imageState.objectUrl); } catch (e) {}
        }

        this.imageState = {
            img: null,
            objectUrl: null,
            naturalWidth: 0,
            naturalHeight: 0,
            fitScale: 1,
            zoom: preserveZoom ? prevZoom : 1,
            panX: 0,
            panY: 0,
            displayWidth: 0,
            displayHeight: 0,
            dragging: false,
            dragStartX: 0,
            dragStartY: 0,
            dragBasePanX: 0,
            dragBasePanY: 0,
        };
    }

    renderCurrentImage() {
        const viewport = document.getElementById("imageViewport");
        const zoomLevel = document.getElementById("zoomLevel");
        if (!viewport || !this.imageState.img || !this.imageState.naturalWidth || !this.imageState.naturalHeight) {
            return;
        }

        const availableWidth = Math.max(1, viewport.clientWidth - 32);
        const availableHeight = Math.max(1, viewport.clientHeight - 32);
        const fitScale = Math.min(
            availableWidth / this.imageState.naturalWidth,
            availableHeight / this.imageState.naturalHeight
        );
        this.imageState.fitScale = fitScale;

        const displayScale = fitScale * this.imageState.zoom;
        const displayWidth = Math.max(1, Math.round(this.imageState.naturalWidth * displayScale));
        const displayHeight = Math.max(1, Math.round(this.imageState.naturalHeight * displayScale));
        this.imageState.displayWidth = displayWidth;
        this.imageState.displayHeight = displayHeight;

        this.clampPanToViewport();

        this.imageState.img.style.width = `${displayWidth}px`;
        this.imageState.img.style.height = `${displayHeight}px`;
        this.imageState.img.style.maxWidth = "none";
        this.imageState.img.style.maxHeight = "none";
        this.imageState.img.style.position = "absolute";
        this.imageState.img.style.left = "50%";
        this.imageState.img.style.top = "50%";
        this.imageState.img.style.transform = `translate(-50%, -50%) translate(${this.imageState.panX || 0}px, ${this.imageState.panY || 0}px)`;
        this.imageState.img.style.pointerEvents = "none";

        viewport.style.cursor = this.imageState.dragging ? "grabbing" : (this.canPanImage() ? "grab" : "default");

        if (zoomLevel) {
            zoomLevel.textContent = `${Math.round(this.imageState.zoom * 100)}%`;
        }
    }

    updateFrameControls() {
        const label = document.getElementById('frameLabel');
        const prevBtn = document.getElementById('framePrevBtn');
        const nextBtn = document.getElementById('frameNextBtn');
        const total = (this.currentDicomMetadata && this.currentDicomMetadata.number_of_frames) ? this.currentDicomMetadata.number_of_frames : 1;
        const current = Math.max(0, this.imageState.currentFrame || 0);
        if (label) label.textContent = `帧 ${current + 1}/${total}`;
        if (prevBtn) prevBtn.disabled = current <= 0;
        if (nextBtn) nextBtn.disabled = current >= (total - 1);
        // 显示或隐藏控件
        const ctrl = document.getElementById('frameControls');
        if (ctrl) {
            if (total > 1) ctrl.style.display = 'inline-flex';
            else ctrl.style.display = 'none';
        }
    }

    async setFrame(n) {
        const total = (this.currentDicomMetadata && this.currentDicomMetadata.number_of_frames) ? this.currentDicomMetadata.number_of_frames : 1;
        const idx = Math.max(0, Math.min(total - 1, n));
        if (idx === this.imageState.currentFrame) return;
        this.clearAnalysisPanel();
        this.imageState.currentFrame = idx;
        this.updateFrameControls();
        if (this.currentDicomMetadata && this.currentFilePath) {
            if (this.seriesFrameCache.has(this.currentFilePath)) {
                await this.renderSeriesFrame(this.currentFilePath, idx, true);
            } else {
                await this.loadImage(this.currentFilePath, idx, true);
            }
        }
    }

    async prevFrame() {
        await this.setFrame((this.imageState.currentFrame || 0) - 1);
    }

    async nextFrame() {
        await this.setFrame((this.imageState.currentFrame || 0) + 1);
    }

    // ============ 文件浏览 ============

    async loadFileTree(path = "") {
        // 优先使用远端缓存（如果存在），避免在本地未同步时显示过时文件
        if (this.remoteCache[path]) {
            const data = this.remoteCache[path];
            const fileTree = document.getElementById("fileTree");
            fileTree.innerHTML = "";

            if (path !== "") {
                const parentPath = path.substring(0, path.lastIndexOf("/"));
                const backItem = document.createElement("div");
                backItem.className = "file-tree-item";
                backItem.innerHTML = '<span class="icon">⬅️</span><span>..</span>';
                backItem.onclick = () => this.loadFileTree(parentPath);
                fileTree.appendChild(backItem);
            }

            for (const item of data.items) {
                const element = document.createElement("div");
                element.className = `file-tree-item ${item.is_dir ? "directory" : item.is_dicom ? "dicom" : "file"}`;
                element.innerHTML = `<span class="icon"></span><span>${this.escapeHtml(item.name)}</span>`;

                if (item.is_dir) {
                    element.onclick = () => this.loadFileTree(item.path);
                } else if (item.is_dicom) {
                    element.onclick = () => this.selectFile(item.path);
                }

                fileTree.appendChild(element);
            }

            this.currentPath = path;
            this.updateBreadcrumb(path);
            return;
        }
        try {
            const response = await this.apiCall(`/api/files/list?path=${encodeURIComponent(path)}`);
            const data = await response.json();

            const fileTree = document.getElementById("fileTree");
            fileTree.innerHTML = "";

            // 添加返回上级目录选项
            if (path !== "") {
                const parentPath = path.substring(0, path.lastIndexOf("/"));
                const backItem = document.createElement("div");
                backItem.className = "file-tree-item";
                backItem.innerHTML = '<span class="icon">⬅️</span><span>..</span>';
                backItem.onclick = () => this.loadFileTree(parentPath);
                fileTree.appendChild(backItem);
            }

            // 列出文件
            for (const item of data.items) {
                const element = document.createElement("div");
                element.className = `file-tree-item ${item.is_dir ? "directory" : item.is_dicom ? "dicom" : "file"}`;
                element.innerHTML = `<span class="icon"></span><span>${this.escapeHtml(item.name)}</span>`;

                if (item.is_dir) {
                    element.onclick = () => this.loadFileTree(item.path);
                } else if (item.is_dicom) {
                    element.onclick = () => this.selectFile(item.path);
                }

                fileTree.appendChild(element);
            }

            this.currentPath = path;
            this.updateBreadcrumb(path);
        } catch (error) {
            console.error("Failed to load file tree:", error);
        }
    }

    updateBreadcrumb(path) {
        const breadcrumb = document.getElementById("breadcrumb");
        const parts = path.split("/").filter((p) => p);
        let html = '<a href="#" onclick="app.loadFileTree(\'\')">根目录</a>';

        let currentPath = "";
        for (const part of parts) {
            currentPath += "/" + part;
            html += ` / <a href="#" onclick="app.loadFileTree('${this.escapeHtml(currentPath)}', false)">${this.escapeHtml(part)}</a>`;
        }

        breadcrumb.innerHTML = html;
    }

    async selectFile(filePath) {
        // 更新UI：选中该文件
        document.querySelectorAll(".file-tree-item").forEach((item) => {
            item.classList.remove("active");
        });
        event.target.closest(".file-tree-item").classList.add("active");

        // 确保文件存在：先尝试本地信息，如果不存在则按需拉取
        try {
            const infoResp = await this.apiCall(`/api/files/info?path=${encodeURIComponent(filePath)}`);
            if (!infoResp.ok) {
                if (infoResp.status === 404) {
                    // 按需拉取
                    await this.apiCall(`/api/sync/fetch?path=${encodeURIComponent(filePath)}`, { method: 'POST' });
                } else {
                    throw new Error('无法获取文件信息');
                }
            }
        } catch (err) {
            console.warn('按需拉取失败或已存在，本地/远程检查继续：', err);
        }

        // 加载元数据
        const metadata = await this.loadMetadata(filePath);
        this.currentDicomMetadata = metadata;
        this.currentFilePath = filePath;

        // 初始化帧状态
        this.imageState.currentFrame = 0;
        this.updateFrameControls();
        this.clearAnalysisPanel();

        if (this.shouldRenderImage(metadata)) {
            try {
                await this.loadSeriesFrames(filePath, metadata);
                await this.renderSeriesFrame(filePath, this.imageState.currentFrame);
            } catch (error) {
                console.warn("整套帧预加载失败，回退到逐帧加载：", error);
                await this.loadImage(filePath, this.imageState.currentFrame);
            }
        } else if (this.isStructuredReport(metadata)) {
            await this.loadReport(filePath, metadata);
        } else {
            this.showImageUnsupportedMessage(metadata);
        }
    }

    isStructuredReport(metadata) {
        const modality = String(metadata?.modality || "").toUpperCase();
        return modality === "SR";
    }

    shouldRenderImage(metadata) {
        if (!metadata) {
            return false;
        }

        const modality = String(metadata.modality || "").toUpperCase();
        if (modality === "SR") {
            return false;
        }

        if (!metadata.rows || !metadata.columns) {
            return false;
        }

        return true;
    }

    showImageUnsupportedMessage(metadata) {
        const viewport = document.getElementById("imageViewport");
        if (!viewport) {
            return;
        }

        const modality = metadata?.modality ? String(metadata.modality).toUpperCase() : "未知";
        const reason = modality === "SR"
            ? "SR 模态不包含像素数据，只能查看报告内容。"
            : "该文件不包含可显示的图像像素数据。";

        viewport.innerHTML = `<div class="message info">${reason}</div>`;
    }

    async loadReport(filePath, metadata) {
        const viewport = document.getElementById("imageViewport");
        if (!viewport) {
            return;
        }

        viewport.innerHTML = '<div class="loading"><div class="spinner"></div><span>正在加载报告...</span></div>';

        try {
            const response = await this.apiCall(`/api/dicom/report?path=${encodeURIComponent(filePath)}`);
            if (!response.ok) {
                throw new Error('无法获取报告');
            }

            const report = await response.json();
            const title = report.title || metadata?.series_description || '结构化报告';
            const text = (report.text || '').trim();

            viewport.innerHTML = `
                <div class="report-view">
                    <div class="report-title">${this.escapeHtml(title)}</div>
                    ${text ? `<div>${this.escapeHtml(text)}</div>` : '<div class="report-empty">未提取到报告正文。</div>'}
                </div>
            `;
        } catch (error) {
            viewport.innerHTML = `<div class="message error">加载报告失败: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    clearAnalysisPanel() {
        const panel = document.getElementById("analysisPanel");
        if (!panel) {
            return;
        }

        panel.classList.add("analysis-panel-hidden");
        panel.innerHTML = "";
    }

    async analyzeCurrentImage() {
        const panel = document.getElementById("analysisPanel");
        if (!panel) {
            return;
        }

        if (!this.currentFilePath || !this.currentDicomMetadata) {
            panel.classList.remove("analysis-panel-hidden");
            panel.innerHTML = '<div class="message info">请先选择一张已展示的图像再进行解析。</div>';
            return;
        }

        if (!this.shouldRenderImage(this.currentDicomMetadata)) {
            panel.classList.remove("analysis-panel-hidden");
            panel.innerHTML = '<div class="message info">当前文件不属于可解析的图像类型。</div>';
            return;
        }

        const frame = this.imageState.currentFrame || 0;
        const modeSelect = document.getElementById("analysisModeSelect");
        const mode = modeSelect && modeSelect.value ? modeSelect.value : "opencv_border_relaxed";
        panel.classList.remove("analysis-panel-hidden");
        panel.innerHTML = `
            <div class="analysis-loading">
                <div class="spinner"></div>
                <span>正在解析当前图像内容...</span>
            </div>
        `;

        try {
            const ocrSelect = document.getElementById("ocrEngineSelect");
            const ocrEngine = ocrSelect && ocrSelect.value ? ocrSelect.value : (this.selectedOCREngine || "tesseract");
            const response = await this.apiCall(
                `/api/dicom/analyze?path=${encodeURIComponent(this.currentFilePath)}&frame=${encodeURIComponent(String(frame))}&mode=${encodeURIComponent(mode)}&ocr_engine=${encodeURIComponent(ocrEngine)}`
            );

            if (!response.ok) {
                let message = "图像解析失败";
                try {
                    const errorData = await response.json();
                    message = errorData.detail || message;
                } catch (parseError) {}
                throw new Error(message);
            }

            const result = await response.json();
            this.renderAnalysisResult(result);
        } catch (error) {
            panel.innerHTML = `<div class="message error">解析失败: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    renderAnalysisResult(result) {
        const panel = document.getElementById("analysisPanel");
        if (!panel) {
            return;
        }

        const text = (result.text || "").trim();
        const diagnosisOpinions = Array.isArray(result.diagnosis_opinions) ? result.diagnosis_opinions : [];
        const warnings = Array.isArray(result.warnings) ? result.warnings : [];
        const regions = Array.isArray(result.regions) ? result.regions : [];

        const regionHtml = regions.length
            ? regions.map((region, index) => `
                <div class="analysis-region">
                    <div class="analysis-region-preview">
                        <img src="data:image/png;base64,${region.image_base64}" alt="提取区域 ${index + 1}">
                    </div>
                    <div class="analysis-region-meta">
                        <div>区域 ${index + 1}</div>
                        <div>${region.width} × ${region.height}，占比 ${(region.area_ratio * 100).toFixed(2)}%</div>
                    </div>
                </div>
            `).join("")
            : '<div class="analysis-empty">未检测到明显的矩形影像区域。</div>';

        const warningHtml = warnings.length
            ? `<div class="analysis-warnings">${warnings.map((item) => `<div class="analysis-warning">${this.escapeHtml(item)}</div>`).join("")}</div>`
            : "";

        const diagnosisText = diagnosisOpinions.length
            ? diagnosisOpinions.map((item, index) => `${index + 1}. ${item}`).join("\n")
            : "";

        panel.innerHTML = `
            <div class="analysis-header">
                <div class="analysis-title">图像解析结果</div>
                <div class="analysis-summary">提取文本 ${text ? "已获得" : "为空"} · 诊断意见 ${diagnosisOpinions.length} 条 · 检测区域 ${regions.length} 个</div>
            </div>
            ${warningHtml}
            <div class="analysis-text-block">
                <div class="analysis-section-title">提取文本</div>
                <div class="analysis-text ${text ? "" : "analysis-region-muted"}">${text ? this.escapeHtml(text) : "未识别到文本"}</div>
            </div>
            <div class="analysis-text-block">
                <div class="analysis-section-title">诊断意见</div>
                <div class="analysis-text ${diagnosisText ? "" : "analysis-region-muted"}">${diagnosisText ? this.escapeHtml(diagnosisText) : "未提取到诊断意见"}</div>
            </div>
            <div class="analysis-text-block">
                <div class="analysis-section-title">提取到的影像图像</div>
                <div class="analysis-grid">
                    ${regionHtml}
                </div>
            </div>
        `;
    }

    async handleRefresh() {
        try {
            const resp = await this.apiCall(`/api/sync/refresh?path=${encodeURIComponent(this.currentPath)}`, { method: 'POST' });
            if (resp.ok) {
                const data = await resp.json();
                // 将远端返回的目录结构写入缓存，覆盖本地显示
                this.remoteCache[this.currentPath] = data;
                // 构建临时显示：直接渲染返回的远端目录结构
                const fileTree = document.getElementById("fileTree");
                fileTree.innerHTML = "";

                if (this.currentPath !== "") {
                    const parentPath = this.currentPath.substring(0, this.currentPath.lastIndexOf("/"));
                    const backItem = document.createElement("div");
                    backItem.className = "file-tree-item";
                    backItem.innerHTML = '<span class="icon">⬅️</span><span>..</span>';
                    backItem.onclick = () => this.loadFileTree(parentPath);
                    fileTree.appendChild(backItem);
                }

                for (const item of data.items) {
                    const element = document.createElement("div");
                    element.className = `file-tree-item ${item.is_dir ? "directory" : item.is_dicom ? "dicom" : "file"}`;
                    element.innerHTML = `<span class="icon"></span><span>${this.escapeHtml(item.name)}</span>`;

                    if (item.is_dir) element.onclick = () => this.loadFileTree(item.path);
                    else if (item.is_dicom) element.onclick = () => this.selectFile(item.path);

                    fileTree.appendChild(element);
                }

            } else {
                console.error('刷新失败', await resp.text());
            }
        } catch (err) {
            console.error('刷新时发生错误', err);
        }
    }

    // ============ DICOM 处理 ============

    async loadMetadata(filePath) {
        const panel = document.getElementById("metadataPanel");

        try {
            const response = await this.apiCall(
                `/api/dicom/metadata?path=${encodeURIComponent(filePath)}`
            );
            const metadata = await response.json();

            panel.innerHTML = this.formatMetadata(metadata);
            return metadata;
        } catch (error) {
            panel.innerHTML = `<div class="message error">加载元数据失败: ${error.message}</div>`;
            return null;
        }
    }

    formatMetadata(metadata) {
        const items = [
            { label: "患者姓名", value: metadata.patient_name },
            { label: "患者 ID", value: metadata.patient_id },
            { label: "检查日期", value: metadata.study_date },
            { label: "模态", value: metadata.modality },
            { label: "序列描述", value: metadata.series_description },
            { label: "实例号", value: metadata.instance_number },
            { label: "图像尺寸", value: metadata.rows && metadata.columns ? `${metadata.columns}×${metadata.rows}` : "N/A" },
            { label: "帧数", value: metadata.number_of_frames || 1 },
            { label: "位数分配", value: metadata.bits_allocated },
            { label: "像素表现", value: metadata.photometric_interpretation },
        ];

        let html = "";
        for (const item of items) {
            if (item.value !== null && item.value !== undefined) {
                html += `
                    <div class="metadata-item">
                        <div class="metadata-label">${this.escapeHtml(item.label)}</div>
                        <div class="metadata-value">${this.escapeHtml(String(item.value))}</div>
                    </div>
                `;
            }
        }

        return html || "<div class='message info'>无元数据</div>";
    }

    async loadImage(filePath, frame = 0, preserveZoom = false) {
        const viewport = document.getElementById("imageViewport");
        if (!viewport) {
            return;
        }

        this.clearImageState(preserveZoom);
        // 优先从前端缓存读取已经请求过的帧（减少重复网络请求）
        const cacheKey = `${filePath}::${frame}`;
        if (this.frameBlobCache.has(cacheKey)) {
            const cachedBlob = this.frameBlobCache.get(cacheKey);
            const cachedUrl = URL.createObjectURL(cachedBlob);
            const img = document.createElement("img");
            img.alt = "DICOM 图像";
            img.src = cachedUrl;
            img.onload = () => {
                viewport.innerHTML = "";
                this.imageState = {
                    img,
                    objectUrl: cachedUrl,
                    naturalWidth: img.naturalWidth || img.width,
                    naturalHeight: img.naturalHeight || img.height,
                    fitScale: 1,
                    zoom: this.imageState.zoom || 1,
                    panX: 0,
                    panY: 0,
                    displayWidth: 0,
                    displayHeight: 0,
                    dragging: false,
                    dragStartX: 0,
                    dragStartY: 0,
                    dragBasePanX: 0,
                    dragBasePanY: 0,
                    currentFrame: frame,
                    playing: false,
                };
                viewport.appendChild(img);
                this.renderCurrentImage();
                this.updateFrameControls();
                // 后台预取相邻帧
                this.prefetchFrames(filePath, frame);
            };
            img.onerror = () => {
                // 如果缓存的 URL 失效，移除并回退到网络加载
                this.frameBlobCache.delete(cacheKey);
                try { URL.revokeObjectURL(cachedUrl); } catch (e) {}
                this.loadImage(filePath, frame, preserveZoom);
            };
            return;
        }

        viewport.innerHTML = '<div class="loading"><div class="spinner"></div><span>加载中...</span></div>';

        try {
            const blob = await this.fetchImageBlob(filePath, frame);
            const objectUrl = URL.createObjectURL(blob);

            const img = document.createElement("img");
            img.alt = "DICOM 图像";
            img.src = objectUrl;

            img.onload = () => {
                viewport.innerHTML = "";
                this.imageState = {
                    img,
                    objectUrl,
                    naturalWidth: img.naturalWidth || img.width,
                    naturalHeight: img.naturalHeight || img.height,
                    fitScale: 1,
                    zoom: this.imageState.zoom || 1,
                    panX: 0,
                    panY: 0,
                    displayWidth: 0,
                    displayHeight: 0,
                    dragging: false,
                    dragStartX: 0,
                    dragStartY: 0,
                    dragBasePanX: 0,
                    dragBasePanY: 0,
                    currentFrame: frame,
                    playing: false,
                };
                viewport.appendChild(img);
                this.renderCurrentImage();
                this.updateFrameControls();
                // 后台预取相邻帧
                this.prefetchFrames(filePath, frame);
            };

            img.onerror = () => {
                try { URL.revokeObjectURL(objectUrl); } catch (e) {}
                viewport.innerHTML = '<div class="message error">无法加载图像</div>';
            };

        } catch (error) {
            viewport.innerHTML = `<div class="message error">加载图像失败: ${error.message}</div>`;
        }
    }

    async loadSeriesFrames(filePath, metadata) {
        if (this.seriesFrameCache.has(filePath)) {
            return this.seriesFrameCache.get(filePath);
        }

        if (this.seriesLoadPromise.has(filePath)) {
            return this.seriesLoadPromise.get(filePath);
        }

        const loadPromise = (async () => {
            const frameCount = (metadata && metadata.number_of_frames) ? metadata.number_of_frames : 1;
            const preferredFormat = frameCount > 1 ? "jpeg" : "png";
            const viewport = document.getElementById("imageViewport");
            if (viewport) {
                viewport.innerHTML = '<div class="loading"><div class="spinner"></div><span>一次性加载整套帧...</span></div>';
            }

            const response = await this.apiCall(
                `/api/dicom/frames?path=${encodeURIComponent(filePath)}&format=${preferredFormat}`
            );

            if (!response.ok) {
                let errorMessage = "无法预加载整套帧";
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || errorMessage;
                } catch (parseError) {}
                throw new Error(errorMessage);
            }

            const series = await response.json();
            const frameUrls = new Array(series.frame_count || frameCount);
            for (const item of series.frames || []) {
                frameUrls[item.frame] = `data:image/${series.format || preferredFormat};base64,${item.data}`;
            }

            const cachedSeries = {
                format: series.format || preferredFormat,
                frameCount: series.frame_count || frameCount,
                width: series.width || metadata?.columns || null,
                height: series.height || metadata?.rows || null,
                frames: frameUrls,
            };
            this.seriesFrameCache.set(filePath, cachedSeries);
            return cachedSeries;
        })();

        this.seriesLoadPromise.set(filePath, loadPromise);
        try {
            return await loadPromise;
        } finally {
            this.seriesLoadPromise.delete(filePath);
        }
    }

    async renderSeriesFrame(filePath, frame) {
        // 保留向后兼容：接受第三个参数 preserveZoom
        const preserveZoom = arguments.length >= 3 ? arguments[2] : false;
        const viewport = document.getElementById("imageViewport");
        if (!viewport) {
            return;
        }
        const series = this.seriesFrameCache.get(filePath);
        if (!series || !series.frames || !series.frames[frame]) {
            viewport.innerHTML = '<div class="message error">帧缓存不存在，请重新加载文件</div>';
            return;
        }
        this.clearImageState(preserveZoom);

        viewport.innerHTML = '<div class="loading"><div class="spinner"></div><span>渲染本地缓存帧...</span></div>';

        const img = document.createElement("img");
        const frameUrl = series.frames[frame];
        img.alt = `DICOM 图像帧 ${frame + 1}`;
        img.src = frameUrl;

        img.onload = () => {
            viewport.innerHTML = "";
            this.imageState = {
                img,
                objectUrl: frameUrl,
                naturalWidth: img.naturalWidth || img.width || series.width || 0,
                naturalHeight: img.naturalHeight || img.height || series.height || 0,
                fitScale: 1,
                zoom: this.imageState.zoom || 1,
                panX: 0,
                panY: 0,
                displayWidth: 0,
                displayHeight: 0,
                dragging: false,
                dragStartX: 0,
                dragStartY: 0,
                dragBasePanX: 0,
                dragBasePanY: 0,
                currentFrame: frame,
                playing: false,
            };
            viewport.appendChild(img);
            this.renderCurrentImage();
            this.updateFrameControls();
        };

        img.onerror = () => {
            viewport.innerHTML = '<div class="message error">本地缓存帧渲染失败</div>';
        };
    }

    // ============ API 调用 ============

    async apiCall(endpoint, options = {}) {
        const headers = {
            ...options.headers,
            Authorization: `Bearer ${this.accessToken}`,
        };

        const response = await fetch(endpoint, {
            ...options,
            headers,
        });

        if (response.status === 401) {
            this.logout();
            throw new Error("Unauthorized");
        }

        return response;
    }

    // ============ 前端帧 blob 缓存与预取 ============
    cachePut(key, objectUrl) {
        if (this.frameBlobCache.has(key)) {
            this.frameBlobCache.delete(key);
        }
        this.frameBlobCache.set(key, objectUrl);
        while (this.frameBlobCache.size > this.maxCachedFrames) {
            const firstKey = this.frameBlobCache.keys().next().value;
            const firstUrl = this.frameBlobCache.get(firstKey);
            try { URL.revokeObjectURL(firstUrl); } catch (e) {}
            this.frameBlobCache.delete(firstKey);
        }
    }

    async fetchImageBlob(filePath, frame) {
        const cacheKey = `${filePath}::${frame}`;
        if (this.frameBlobCache.has(cacheKey)) {
            return this.frameBlobCache.get(cacheKey);
        }

        const resp = await this.apiCall(`/api/dicom/image?path=${encodeURIComponent(filePath)}&format=png&frame=${encodeURIComponent(String(frame))}`);
        if (!resp.ok) {
            let errMsg = '无法加载图像';
            try { const j = await resp.json(); errMsg = j.detail || errMsg; } catch (e) {}
            throw new Error(errMsg);
        }

        const blob = await resp.blob();
        this.cachePut(cacheKey, blob);
        return blob;
    }

    prefetchFrames(filePath, frame) {
        const total = (this.currentDicomMetadata && this.currentDicomMetadata.number_of_frames) ? this.currentDicomMetadata.number_of_frames : 1;
        const offsets = [1, -1, 2, -2];
        for (const off of offsets) {
            const idx = frame + off;
            if (idx < 0 || idx >= total) continue;
            const key = `${filePath}::${idx}`;
            if (this.frameBlobCache.has(key)) continue;
            this.fetchImageBlob(filePath, idx).catch(() => {});
        }
    }

    // ============ 工具函数 ============

    escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }
}

// 初始化应用
const app = new DicomViewerApp();
