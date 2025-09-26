import asyncio
import time
import json
import psutil
import rusty_req
from rusty_req import ConcurrencyMode
from typing import Dict, Any
import aiohttp
import httpx
import requests
from concurrent.futures import ThreadPoolExecutor
import os


class PerformanceTest:
    def __init__(self):
        self.test_results = {}
        self.httpbin_url = os.getenv('HTTPBIN_URL', 'http://localhost:8080')
        print(f"🌐 使用 httpbin 服务地址: {self.httpbin_url}")

    async def cooldown(self, seconds: int = 10):
        """测试间隔冷却"""
        print(f"⏳ 冷却 {seconds} 秒，等待 httpbin 恢复...")
        await asyncio.sleep(seconds)
        # 如果你用 docker 跑 httpbin，可以替换为:
        # os.system("docker restart httpbin")

    async def test_httpbin_connectivity(self):
        """测试 httpbin 服务连接性"""
        print("🔍 测试 httpbin 服务连接...")

        try:
            response = await rusty_req.fetch_single(
                url=f"{self.httpbin_url}/status/200",
                method="GET",
                timeout=5.0
            )
            print(f"📝 httpbin 响应详情: {response}")

            http_status = response.get("http_status")
            if isinstance(http_status, str):
                http_status = int(http_status) if http_status.isdigit() else 0

            exception = response.get("exception", {})
            if isinstance(exception, str):
                try:
                    exception = json.loads(exception)
                except json.JSONDecodeError:
                    exception = {}

            has_error = exception.get("type") is not None

            if http_status == 200 and not has_error:
                print("✅ httpbin 服务连接正常")
                return True
            else:
                print(f"❌ httpbin 服务响应异常 - 状态码: {http_status}, 错误: {exception}")
                return False

        except Exception as e:
            print(f"❌ httpbin 服务连接失败: {e}")
            return False

    async def test_rusty_req_batch(self, num_requests: int = 100, delay: float = 1.0) -> Dict[str, Any]:
        print(f"🚀 测试 rusty-req 批量请求 ({num_requests} 个请求, 延迟 {delay}s)...")

        requests_list = [
            rusty_req.RequestItem(
                url=f"{self.httpbin_url}/delay/{delay}",
                method="GET",
                timeout=delay + 2.0,
                tag=f"batch-req-{i}",
            )
            for i in range(num_requests)
        ]

        process = psutil.Process()
        start_memory = process.memory_info().rss / 1024 / 1024

        start_time = time.perf_counter()
        responses = await rusty_req.fetch_requests(
            requests_list,
            total_timeout=delay + 5.0,
            mode=ConcurrencyMode.SELECT_ALL
        )
        end_time = time.perf_counter()
        end_memory = process.memory_info().rss / 1024 / 1024

        successful = 0
        failed = 0
        for r in responses:
            http_status = r.get("http_status")
            if isinstance(http_status, str):
                http_status = int(http_status) if http_status.isdigit() else 0

            exception = r.get("exception", {})
            if isinstance(exception, str):
                try:
                    exception = json.loads(exception) if exception else {}
                except json.JSONDecodeError:
                    exception = {}

            has_error = exception.get("type") is not None
            if http_status == 200 and not has_error:
                successful += 1
            else:
                failed += 1

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
            "avg_response_time": total_time / num_requests
        }

    async def test_rusty_req_single(self, num_requests: int = 100, delay: float = 1.0) -> Dict[str, Any]:
        print(f"🚀 测试 rusty-req 单个请求 ({num_requests} 个请求, 延迟 {delay}s)...")

        start_time = time.perf_counter()
        successful = 0
        failed = 0

        tasks = [
            rusty_req.fetch_single(
                url=f"{self.httpbin_url}/delay/{delay}",
                method="GET",
                timeout=delay + 2.0,
                tag=f"single-req-{i}"
            )
            for i in range(num_requests)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.perf_counter()

        for response in responses:
            if isinstance(response, Exception):
                failed += 1
            elif isinstance(response, dict):
                http_status = response.get("http_status")
                if isinstance(http_status, str):
                    http_status = int(http_status) if http_status.isdigit() else 0

                exception = response.get("exception", {})
                if isinstance(exception, str):
                    try:
                        exception = json.loads(exception) if exception else {}
                    except json.JSONDecodeError:
                        exception = {}

                has_error = exception.get("type") is not None
                if http_status == 200 and not has_error:
                    successful += 1
                else:
                    failed += 1
            else:
                failed += 1

        total_time = end_time - start_time

        return {
            "library": "rusty-req",
            "mode": "single",
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / num_requests) * 100,
            "total_time": total_time,
            "requests_per_second": num_requests / total_time,
            "avg_response_time": total_time / num_requests
        }

    async def test_httpx_async(self, num_requests: int = 100, delay: float = 1.0) -> Dict[str, Any]:
        print(f"🚀 测试 httpx 异步请求 ({num_requests} 个请求, 延迟 {delay}s)...")

        start_time = time.perf_counter()
        successful = 0
        failed = 0

        timeout = httpx.Timeout(delay + 2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            tasks = [client.get(f"{self.httpbin_url}/delay/{delay}") for _ in range(num_requests)]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.perf_counter()

        for response in responses:
            if isinstance(response, Exception):
                failed += 1
            elif hasattr(response, 'status_code') and response.status_code == 200:
                successful += 1
            else:
                failed += 1

        total_time = end_time - start_time

        return {
            "library": "httpx",
            "mode": "async",
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / num_requests) * 100,
            "total_time": total_time,
            "requests_per_second": num_requests / total_time,
            "avg_response_time": total_time / num_requests
        }

    async def test_aiohttp(self, num_requests: int = 100, delay: float = 1.0) -> Dict[str, Any]:
        print(f"🚀 测试 aiohttp ({num_requests} 个请求, 延迟 {delay}s)...")

        start_time = time.perf_counter()
        successful = 0
        failed = 0

        timeout = aiohttp.ClientTimeout(total=delay + 2.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [session.get(f"{self.httpbin_url}/delay/{delay}") for _ in range(num_requests)]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.perf_counter()

        for response in responses:
            if isinstance(response, Exception):
                failed += 1
            else:
                try:
                    if hasattr(response, 'status') and response.status == 200:
                        successful += 1
                    else:
                        failed += 1
                finally:
                    if hasattr(response, 'close'):
                        response.close()

        total_time = end_time - start_time

        return {
            "library": "aiohttp",
            "mode": "async",
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / num_requests) * 100,
            "total_time": total_time,
            "requests_per_second": num_requests / total_time,
            "avg_response_time": total_time / num_requests
        }

    def test_requests_sync(self, num_requests: int = 50, delay: float = 1.0) -> Dict[str, Any]:
        print(f"🚀 测试 requests 同步请求 ({num_requests} 个请求, 延迟 {delay}s)...")

        def make_request():
            try:
                response = requests.get(f"{self.httpbin_url}/delay/{delay}", timeout=delay + 2.0)
                return response.status_code == 200
            except Exception:
                return False

        start_time = time.perf_counter()

        with ThreadPoolExecutor(max_workers=min(50, num_requests)) as executor:
            results = list(executor.map(lambda _: make_request(), range(num_requests)))

        end_time = time.perf_counter()

        successful = sum(results)
        failed = num_requests - successful
        total_time = end_time - start_time

        return {
            "library": "requests",
            "mode": "sync_threaded",
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / num_requests) * 100,
            "total_time": total_time,
            "requests_per_second": num_requests / total_time,
            "avg_response_time": total_time / num_requests
        }

    async def run_comprehensive_test(self):
        print("=" * 60)
        print("🎯 开始 rusty-req 综合性能测试")
        print("=" * 60)

        if not await self.test_httpbin_connectivity():
            print("❌ httpbin 服务不可用，测试终止")
            return {}

        rusty_req.set_debug(False)
        results = {}

        try:
            # rusty-req 批量
            print("\n📊 批量请求性能测试")
            result = await self.test_rusty_req_batch(50, 0.5)
            results["rusty_req_batch"] = result
            print("   ✅ 完成批量请求性能测试")
            await self.cooldown(10)

            # rusty-req 单个
            print("\n📊 单个请求性能测试")
            result = await self.test_rusty_req_single(50, 0.5)
            results["rusty_req_single"] = result
            print("   ✅ 完成单个请求性能测试")
            await self.cooldown(10)

            # httpx
            print("\n📊 httpx 性能测试")
            try:
                results["httpx_async"] = await self.test_httpx_async(50, 0.5)
                print("   ✅ 完成 httpx 测试")
            except Exception as e:
                print(f"   ⚠️ httpx 测试失败: {e}")
            await self.cooldown(10)

            # aiohttp
            print("\n📊 aiohttp 性能测试")
            try:
                results["aiohttp"] = await self.test_aiohttp(50, 0.5)
                print("   ✅ 完成 aiohttp 测试")
            except Exception as e:
                print(f"   ⚠️ aiohttp 测试失败: {e}")
            await self.cooldown(10)

            # requests
            print("\n📊 requests 性能测试")
            try:
                results["requests_sync"] = self.test_requests_sync(30, 0.5)
                print("   ✅ 完成 requests 测试")
            except Exception as e:
                print(f"   ⚠️ requests 测试失败: {e}")
            await self.cooldown(10)

        except Exception as e:
            print(f"❌ 测试过程中发生错误: {e}")
            import traceback
            traceback.print_exc()

        return results

    def print_results(self, results: Dict[str, Any]):
        print("\n" + "=" * 80)
        print("📋 性能测试报告")
        print("=" * 80)

        for test_name, result in results.items():
            print(f"\n📊 {result['library']} ({result.get('mode', 'default')}):")
            print(f"   总请求数: {result['total_requests']}")
            print(f"   成功请求: {result['successful']}")
            print(f"   失败请求: {result['failed']}")
            print(f"   成功率: {result['success_rate']:.1f}%")
            print(f"   总耗时: {result['total_time']:.2f} 秒")
            print(f"   请求速率: {result['requests_per_second']:.1f} req/s")
            print(f"   平均响应时间: {result['avg_response_time']*1000:.1f} ms")
            if 'memory_usage' in result:
                print(f"   内存使用: {result['memory_usage']:.1f} MB")

        print(f"\n🏆 性能排行 (按请求速率):")
        performance_data = []
        for result in results.values():
            if 'requests_per_second' in result:
                performance_data.append(
                    (f"{result['library']}({result.get('mode', 'default')})",
                     result['requests_per_second'],
                     result['success_rate'])
                )

        performance_data.sort(key=lambda x: x[1], reverse=True)
        for i, (lib, rps, success_rate) in enumerate(performance_data, 1):
            print(f"   {i}. {lib}: {rps:.1f} req/s (成功率: {success_rate:.1f}%)")


async def main():
    tester = PerformanceTest()

    try:
        results = await tester.run_comprehensive_test()
        if not results:
            print("❌ 测试失败，无结果数据")
            return

        tester.print_results(results)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"rusty_req_benchmark_{timestamp}.json"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\n💾 测试结果已保存到 {filename}")

    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        import rusty_req
        print("✅ 所有依赖库检查通过")
    except ImportError as e:
        print(f"❌ 缺少依赖库: {e}")
        print("请安装: pip install rusty-req")
        exit(1)

    optional_deps = []
    try:
        import aiohttp
        optional_deps.append("aiohttp")
    except ImportError:
        print("⚠️ aiohttp 未安装，将跳过相关测试")

    try:
        import httpx
        optional_deps.append("httpx")
    except ImportError:
        print("⚠️ httpx 未安装，将跳过相关测试")

    try:
        import requests
        optional_deps.append("requests")
    except ImportError:
        print("⚠️ requests 未安装，将跳过相关测试")

    try:
        import psutil
        optional_deps.append("psutil")
    except ImportError:
        print("⚠️ psutil 未安装，将跳过内存监控")

    if optional_deps:
        print(f"✅ 可选依赖已安装: {', '.join(optional_deps)}")

    asyncio.run(main())
