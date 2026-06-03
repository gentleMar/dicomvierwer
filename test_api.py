"""
测试脚本
用于测试 API 和各项功能
"""

import requests
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"
USERNAME = "admin"
PASSWORD = "admin123"

class DicomViewerTester:
    def __init__(self):
        self.token = None
        self.session = requests.Session()
    
    def test_login(self):
        """测试登录"""
        print("\n=== 测试登录 ===")
        response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": USERNAME, "password": PASSWORD}
        )
        print(f"状态码: {response.status_code}")
        if response.ok:
            data = response.json()
            self.token = data.get("access_token")
            print(f"✓ 登录成功")
            print(f"  令牌: {self.token[:20]}...")
        else:
            print(f"✗ 登录失败: {response.text}")
    
    def test_get_user_info(self):
        """测试获取用户信息"""
        print("\n=== 测试获取用户信息 ===")
        headers = {"Authorization": f"Bearer {self.token}"}
        response = self.session.get(
            f"{BASE_URL}/api/auth/me",
            headers=headers
        )
        print(f"状态码: {response.status_code}")
        if response.ok:
            data = response.json()
            print(f"✓ 获取成功")
            print(f"  用户名: {data.get('username')}")
            print(f"  邮箱: {data.get('email')}")
        else:
            print(f"✗ 获取失败: {response.text}")
    
    def test_list_directory(self):
        """测试列表目录"""
        print("\n=== 测试列表目录 ===")
        headers = {"Authorization": f"Bearer {self.token}"}
        
        # 列表根目录
        response = self.session.get(
            f"{BASE_URL}/api/files/list?path=",
            headers=headers
        )
        print(f"状态码: {response.status_code}")
        if response.ok:
            data = response.json()
            print(f"✓ 列表成功")
            print(f"  路径: {data.get('path')}")
            print(f"  项数: {data.get('total')}")
            print(f"  文件:")
            for item in data.get("items", [])[:5]:
                print(f"    - {item['name']} ({'目录' if item['is_dir'] else '文件'})")
        else:
            print(f"✗ 列表失败: {response.text}")
    
    def test_health_check(self):
        """测试健康检查"""
        print("\n=== 测试健康检查 ===")
        response = self.session.get(f"{BASE_URL}/api/health")
        print(f"状态码: {response.status_code}")
        if response.ok:
            data = response.json()
            print(f"✓ 健康检查通过")
            print(f"  状态: {data.get('status')}")
            print(f"  应用: {data.get('app')}")
        else:
            print(f"✗ 健康检查失败")
    
    def test_main_page(self):
        """测试主页面"""
        print("\n=== 测试主页面 ===")
        response = self.session.get(f"{BASE_URL}/")
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            print(f"✓ 主页面加载成功")
        else:
            print(f"✗ 主页面加载失败")
    
    def run_all_tests(self):
        """运行所有测试"""
        print("╔══════════════════════════════════════════╗")
        print("║    DICOM Viewer API 测试               ║")
        print("╚══════════════════════════════════════════╝")
        
        try:
            self.test_health_check()
            self.test_main_page()
            self.test_login()
            
            if self.token:
                self.test_get_user_info()
                self.test_list_directory()
            
            print("\n╔══════════════════════════════════════════╗")
            print("║    所有测试完成                         ║")
            print("╚══════════════════════════════════════════╝")
        except Exception as e:
            print(f"\n✗ 测试出错: {e}")


if __name__ == "__main__":
    import time
    
    print("等待服务启动...")
    time.sleep(2)
    
    tester = DicomViewerTester()
    tester.run_all_tests()
