import asyncio
import time
import statistics
import json
import psutil
import rusty_req
from rusty_req import ConcurrencyMode
from typing import List, Dict, Any
import aiohttp
import httpx
import requests
from concurrent.futures import ThreadPoolExecutor
import os


class PerformanceTest:
    def __init__(self):
        self.test_results = {}
        # 从环境变量获取 httpbin URL，默认使用本地服务
        self.httpbin_url = os.getenv('HTTPBIN_URL', 'http://localhost:8080')
        print(f"🌐 使用 httpbin 服务地址: {self.httpbin_url}")
        
    async def test_rusty_req_batch(self, num_requests: int = 1000, delay: float = 2.0) -> Dict[str, Any]:
        """测试 rusty-req 批量请求性能"""
        print(f"🚀 测试 rusty-req 批量请求 ({num_requests} 个请求)...")
        
        # 创建请求列表，使用本地 httpbin 服务
        requests_list = [
            rusty_req.RequestItem(
                url=f"{self.httpbin_url}/delay/{delay}",
                method="GET",
                timeout=delay + 1.0,
                tag=f"batch-req-{i}",
            )
            for i in range(num_requests)
        ]
        
        # 监控系统资源
        process = psutil.Process()
        start_memory = process.memory_info().rss / 1024 / 1024  # MB
        start_cpu = process.cpu_percent()
        
        start_time = time.perf_counter()
        
        # 执行批量请求
        responses = await rusty_req.fetch_requests(
            requests_list,
            total_timeout=delay + 2.0,
            mode=ConcurrencyMode.SELECT_ALL
        )
        
        end_time = time.perf_counter()
        end_memory = process.memory_info().rss / 1024 / 1024  # MB
        end_cpu = process.cpu_percent()
        
        # 分析结果
        successful = sum(1 for r in responses if not r.get("exception", {}).get("type"))
        failed = len(responses) - successful
        
        total_time = end_time - start_time
        
        return {
            "library": "rusty-req",
            "mode": "batch",
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / num_requests) * 100,
            "total_time": total_time,
            "requests_per_second": num_requests / total_time,
            "memory_usage": end_memory - start_memory,
            "cpu_usage": end_cpu - start_cpu
        }
    
    async def test_httpbin_connectivity(self):
        """测试 httpbin 服务连接性"""
        print("🔍 测试 httpbin 服务连接...")
        
        try:
            # 测试基本连接
            response = await rusty_req.fetch_single(
                url=f"{self.httpbin_url}/status/200",
                method="GET",
                timeout=5.0
            )
            
            if response.get("http_status") == 200:
                print("✅ httpbin 服务连接正常")
                return True
            else:
                print(f"❌ httpbin 服务响应异常: {response}")
                return False
                
        except Exception as e:
            print(f"❌ httpbin 服务连接失败: {e}")
            return False
    
    async def test_rusty_req_single(self, num_requests: int = 100, delay: float = 1.0) -> Dict[str, Any]:
        """测试 rusty-req 单个请求性能"""
        print(f"🚀 测试 rusty-req 单个请求 ({num_requests} 个请求)...")
        
        start_time = time.perf_counter()
        successful = 0
        failed = 0
        
        tasks = []
        for i in range(num_requests):
            task = rusty_req.fetch_single(
                url=f"{self.httpbin_url}/delay/{delay}",
                method="GET",
                timeout=delay + 1.0,
                tag=f"single-req-{i}"
            )
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.perf_counter()
        
        for response in responses:
            if isinstance(response, Exception) or (isinstance(response, dict) and response.get("exception", {}).get("type")):
                failed += 1
            else:
                successful += 1
        
        total_time = end_time - start_time
        
        return {
            "library": "rusty-req",
            "mode": "single",
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / num_requests) * 100,
            "total_time": total_time,
            "requests_per_second": num_requests / total_time
        }
    
    async def test_httpx_async(self, num_requests: int = 100, delay: float = 1.0) -> Dict[str, Any]:
        """测试 httpx 异步性能"""
        print(f"🚀 测试 httpx 异步请求 ({num_requests} 个请求)...")
        
        start_time = time.perf_counter()
        successful = 0
        failed = 0
        
        async with httpx.AsyncClient(timeout=delay + 1.0) as client:
            tasks = [
                client.get(f"{self.httpbin_url}/delay/{delay}")
                for _ in range(num_requests)
            ]
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.perf_counter()
        
        for response in responses:
            if isinstance(response, Exception) or (hasattr(response, 'status_code') and response.status_code != 200):
                failed += 1
            else:
                successful += 1
        
        total_time = end_time - start_time
        
        return {
            "library": "httpx",
            "mode": "async",
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / num_requests) * 100,
            "total_time": total_time,
            "requests_per_second": num_requests / total_time
        }
    
    async def test_concurrency_modes(self, num_requests: int = 50) -> Dict[str, Any]:
        """测试不同并发模式的性能差异"""
        print(f"🚀 测试并发模式对比...")
        
        # 创建请求（包含一个会失败的请求）
        requests_list = [
            rusty_req.RequestItem(
                url=f"{self.httpbin_url}/delay/1",
                method="GET",
                timeout=2.0,
                tag=f"success-req-{i}",
            )
            for i in range(num_requests - 1)
        ]
        
        # 添加一个会失败的请求
        requests_list.append(
            rusty_req.RequestItem(
                url=f"{self.httpbin_url}/status/500",
                method="GET",
                timeout=2.0,
                tag="fail-req",
            )
        )
        
        results = {}
        
        # 测试 SELECT_ALL 模式
        start_time = time.perf_counter()
        select_all_responses = await rusty_req.fetch_requests(
            requests_list,
            mode=ConcurrencyMode.SELECT_ALL,
            total_timeout=3.0
        )
        select_all_time = time.perf_counter() - start_time
        
        select_all_success = sum(1 for r in select_all_responses if not r.get("exception", {}).get("type"))
        
        results["SELECT_ALL"] = {
            "successful": select_all_success,
            "failed": len(select_all_responses) - select_all_success,
            "total_time": select_all_time,
            "mode_behavior": "best_effort"
        }
        
        # 测试 JOIN_ALL 模式
        start_time = time.perf_counter()
        join_all_responses = await rusty_req.fetch_requests(
            requests_list,
            mode=ConcurrencyMode.JOIN_ALL,
            total_timeout=3.0
        )
        join_all_time = time.perf_counter() - start_time
        
        join_all_success = sum(1 for r in join_all_responses if not r.get("exception", {}).get("type"))
        
        results["JOIN_ALL"] = {
            "successful": join_all_success,
            "failed": len(join_all_responses) - join_all_success,
            "total_time": join_all_time,
            "mode_behavior": "all_or_nothing"
        }
        
        return results
    
    async def run_comprehensive_test(self):
        """运行综合性能测试"""
        print("=" * 60)
        print("🎯 开始 rusty-req 综合性能测试")
        print("=" * 60)
        
        # 首先测试 httpbin 连接性
        if not await self.test_httpbin_connectivity():
            print("❌ httpbin 服务不可用，测试终止")
            return {}
        
        # 启用调试模式
        rusty_req.set_debug(False)  # 关闭调试输出以获得更好的性能
        
        results = {}
        
        # 1. 批量请求测试（适当调整规模以适应本地测试）
        print("\n📊 批量请求性能测试")
        for num_requests in [50, 200, 500]:  # 降低测试规模
            result = await self.test_rusty_req_batch(num_requests, 0.5)  # 减少延迟时间
            results[f"rusty_req_batch_{num_requests}"] = result
        
        # 2. 单个请求测试
        print("\n📊 单个请求性能测试")
        result = await self.test_rusty_req_single(50, 0.5)
        results["rusty_req_single"] = result
        
        # 3. 与其他库对比测试
        print("\n📊 与其他 HTTP 库性能对比")
        results["httpx_async"] = await self.test_httpx_async(50, 0.5)
        
        # 4. 并发模式测试
        print("\n📊 并发模式对比测试")
        results["concurrency_modes"] = await self.test_concurrency_modes(10)
        
        return results
    
    def print_results(self, results: Dict[str, Any]):
        """打印测试结果"""
        print("\n" + "=" * 80)
        print("📋 性能测试报告")
        print("=" * 80)
        
        # 基础性能测试结果
        print("\n🚀 基础性能测试:")
        basic_tests = [k for k in results.keys() if k.startswith(('rusty_req', 'httpx', 'aiohttp', 'requests'))]
        
        for test_name in basic_tests:
            if test_name == "concurrency_modes":
                continue
            result = results[test_name]
            print(f"\n📊 {result['library']} ({result.get('mode', 'default')}):")
            print(f"   总请求数: {result['total_requests']}")
            print(f"   成功请求: {result['successful']}")
            print(f"   失败请求: {result['failed']}")
            print(f"   成功率: {result['success_rate']:.2f}%")
            print(f"   总耗时: {result['total_time']:.2f} 秒")
            print(f"   请求速率: {result['requests_per_second']:.2f} req/s")
            
            if 'memory_usage' in result:
                print(f"   内存使用: {result['memory_usage']:.2f} MB")
        
        # 并发模式测试结果
        if "concurrency_modes" in results:
            print(f"\n🔄 并发模式对比:")
            modes = results["concurrency_modes"]
            for mode_name, mode_result in modes.items():
                print(f"\n   {mode_name} 模式:")
                print(f"     成功请求: {mode_result['successful']}")
                print(f"     失败请求: {mode_result['failed']}")
                print(f"     耗时: {mode_result['total_time']:.2f} 秒")
                print(f"     行为: {mode_result['mode_behavior']}")
        
        # 性能排行
        print(f"\n🏆 性能排行 (按请求速率):")
        performance_data = []
        for test_name, result in results.items():
            if isinstance(result, dict) and 'requests_per_second' in result:
                performance_data.append((result['library'], result['requests_per_second'], result['success_rate']))
        
        performance_data.sort(key=lambda x: x[1], reverse=True)
        for i, (lib, rps, success_rate) in enumerate(performance_data, 1):
            print(f"   {i}. {lib}: {rps:.2f} req/s (成功率: {success_rate:.2f}%)")


async def main():
    """主函数"""
    tester = PerformanceTest()
    
    try:
        # 运行综合测试
        results = await tester.run_comprehensive_test()
        
        if not results:
            print("❌ 测试失败，无结果数据")
            return
        
        # 打印结果
        tester.print_results(results)
        
        # 保存结果到文件
        with open("rusty_req_performance_test.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 测试结果已保存到 rusty_req_performance_test.json")
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 检查必要的依赖
    try:
        import rusty_req
        import aiohttp
        import httpx
        import requests
        import psutil
        print("✅ 所有依赖库检查通过")
    except ImportError as e:
        print(f"❌ 缺少依赖库: {e}")
        print("请安装: pip install rusty-req aiohttp httpx requests psutil")
        exit(1)
    
    # 运行测试
    asyncio.run(main())
