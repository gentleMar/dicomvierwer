# DICOM Viewer

远程 DICOM 文件浏览与查看系统。附带文字图像提取功能测试。

## 使用前准备

1. 确保已经安装并激活正确的 Python 虚拟环境。
2. 安装依赖并启用虚拟环境：

```bash
uv sync

# macOS / Linux
source .venv/bin/activate

# Windows (CMD)
.venv\Scripts\activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

```

3. 将 `.env.example` 复制为 `.env`，并按具体环境修改下面这些关键项：
	- `REMOTE_HOST`
	- `REMOTE_USER`
	- `REMOTE_DICOM_DIR`

4. 远程服务器需要 ssh 信任本机。

5. 文件默认加载到内存不保存，如需保存修改 FETCH_MODE 为 disk，并指定 LOCAL_SYNC_DIR。
   
6. Tesseract OCR 需要自行安装并配置 TESSERACT_CMD，Paddle OCR 会自动安装，第一次使用需要等待一段时间。

## 启动服务

```bash
python start.py
```

启动后默认访问 Web 页面：http://localhost:8000

## 默认账号

如果没有修改 `.env` 中的用户配置，默认账号密码为：

- 用户名：`admin`
- 密码：`admin123`
