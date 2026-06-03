#!/usr/bin/env python3
"""
DICOM Viewer 项目快速启动脚本
这个脚本仅启动应用，默认当前环境已经配置正确
"""

import sys
import subprocess


def main():
    print("""
    ╔════════════════════════════════════════════════════╗
    ║   DICOM Viewer - 快速启动                          ║
    ║   远程 DICOM 文件浏览与查看系统                    ║
    ╚════════════════════════════════════════════════════╝
    """)

    print("""
    ╔════════════════════════════════════════════════════╗
    ║   启动应用...                                      ║
    ║                                                    ║
    ║   🌐 http://localhost:8000                         ║
    ║   📖 http://localhost:8000/api/docs                ║
    ║                                                    ║
    ║   用户名: admin                                    ║
    ║   密码: admin123                                   ║
    ║                                                    ║
    ║   按 Ctrl+C 停止服务                               ║
    ╚════════════════════════════════════════════════════╝
    """)

    subprocess.run([sys.executable, "-m", "app.main"], check=False)


if __name__ == "__main__":
    main()
