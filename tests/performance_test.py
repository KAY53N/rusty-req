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

# Global settings
GLOBAL_CONCURRENCY = 800
TOTAL_TIMEOUT = 5.0  # Total timeout for all requests
REQUEST_TIMEOUT = 4.5  # Timeout per request

class PerformanceTest:
    def __init__(self):
        self.test_results = {}
        self.httpbin_url = os.getenv('HTTPBIN_URL', 'http://localhost:8080')
        print(f"🌐 Using httpbin service URL: {self.httpbin_url}")

    async def cooldown(self, seconds: int = 10):
        """Cooldown between tests"""
        print(f"⏳ Cooling down for {seconds} seconds...")
        await asyncio.sleep(seconds)

    async def test_httpbin_connectivity(self):
        """Check httpbin connectivity"""
        print("🔍 Testing httpbin connectivity...")
        try:
            response = await rusty_req.fetch_single(
                url=f"{self.httpbin_url}/status/200",
                method="GET",
                timeout=REQUEST_TIMEOUT
            )
            print(f"📝 httpbin response details: {response}")

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
                print("✅ httpbin connectivity OK")
                return True
            else:
                print(f"❌ httpbin abnormal response - status: {http_status}, error: {exception}")
                return False
        except Exception as e:
            print(f"❌ httpbin connectivity failed: {e}")
            return False

    async def test_rusty_req_batch(self, num_requests: int = 100, delay: float = 1.0) -> Dict[str, Any]:
        print(f"🚀 Testing rusty-req batch ({num_requests} requests, {delay}s delay)...")
        requests_list = [
            rusty_req.RequestItem(
                url=f"{self.httpbin_url}/delay/{delay}",
                method="GET",
                timeout=REQUEST_TIMEOUT,
                tag=f"batch-req-{i}",
            )
            for i in range(num_requests)
        ]

        process = psutil.Process()
        start_memory = process.memory_info().rss / 1024 / 1024

        start_time = time.perf_counter()
        responses = await rusty_req.fetch_requests(
            requests_list,
            total_timeout=TOTAL_TIMEOUT,
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

    async def test_httpx_async(self, num_requests: int = 100, delay: float = 1.0) -> Dict[str, Any]:
        print(f"🚀 Testing httpx async ({num_requests} requests, {delay}s delay)...")
        start_time = time.perf_counter()
        successful = 0
        failed = 0

        timeout = httpx.Timeout(REQUEST_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout) as client:
            tasks = [client.get(f"{self.httpbin_url}/delay/{delay}") for _ in range(num_requests)]
            try:
                responses = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=TOTAL_TIMEOUT
                )
            except asyncio.TimeoutError:
                print("⏱ Total timeout exceeded, counting remaining requests as failed")
                responses = []

        for response in responses:
            if isinstance(response, Exception):
                failed += 1
            elif hasattr(response, 'status_code') and response.status_code == 200:
                successful += 1
            else:
                failed += 1

        total_time = min(time.perf_counter() - start_time, TOTAL_TIMEOUT)

        # Count requests not returned due to timeout as failed
        failed += max(0, num_requests - (successful + failed))

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
        print(f"🚀 Testing aiohttp ({num_requests} requests, {delay}s delay)...")
        start_time = time.perf_counter()
        successful = 0
        failed = 0

        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [session.get(f"{self.httpbin_url}/delay/{delay}") for _ in range(num_requests)]
            try:
                responses = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=TOTAL_TIMEOUT
                )
            except asyncio.TimeoutError:
                print("⏱ Total timeout exceeded, counting remaining requests as failed")
                responses = []

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

        total_time = min(time.perf_counter() - start_time, TOTAL_TIMEOUT)
        failed += max(0, num_requests - (successful + failed))

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
        print(f"🚀 Testing requests sync ({num_requests} requests, {delay}s delay)...")

        def make_request():
            try:
                response = requests.get(f"{self.httpbin_url}/delay/{delay}", timeout=REQUEST_TIMEOUT)
                return response.status_code == 200
            except Exception:
                return False

        start_time = time.perf_counter()
        with ThreadPoolExecutor(max_workers=min(GLOBAL_CONCURRENCY, num_requests)) as executor:
            results = list(executor.map(lambda _: make_request(), range(num_requests)))
        end_time = time.perf_counter()

        successful = sum(results)
        failed = num_requests - successful
        total_time = min(end_time - start_time, TOTAL_TIMEOUT)
        failed += max(0, num_requests - (successful + failed))

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
        print("🎯 Start performance benchmark")
        print("=" * 60)

        if not await self.test_httpbin_connectivity():
            print("❌ httpbin service not available, aborting tests")
            return {}

        rusty_req.set_debug(False)
        results = {}

        try:
            # rusty-req batch
            print("\n📊 Rusty-Req batch performance test")
            result = await self.test_rusty_req_batch(500, 0.5)
            results["rusty_req_batch"] = result
            await self.cooldown(10)

            # httpx async
            print("\n📊 httpx performance test")
            try:
                results["httpx_async"] = await self.test_httpx_async(500, 0.5)
            except Exception as e:
                print(f"⚠️ httpx test failed: {e}")
            await self.cooldown(10)

            # aiohttp async
            print("\n📊 aiohttp performance test")
            try:
                results["aiohttp"] = await self.test_aiohttp(500, 0.5)
            except Exception as e:
                print(f"⚠️ aiohttp test failed: {e}")
            await self.cooldown(10)

            # requests sync
            print("\n📊 requests performance test")
            try:
                results["requests_sync"] = self.test_requests_sync(500, 0.5)
            except Exception as e:
                print(f"⚠️ requests test failed: {e}")
            await self.cooldown(10)

        except Exception as e:
            print(f"❌ Error during tests: {e}")
            import traceback
            traceback.print_exc()

        return results

    def print_results(self, results: Dict[str, Any]):
        print("\n" + "=" * 80)
        print("📋 Benchmark Report")
        print("=" * 80)

        for test_name, result in results.items():
            print(f"\n📊 {result['library']} ({result.get('mode', 'default')}):")
            print(f"   Total Requests: {result['total_requests']}")
            print(f"   Successful: {result['successful']}")
            print(f"   Failed: {result['failed']}")
            print(f"   Success Rate: {result['success_rate']:.1f}%")
            print(f"   Total Time: {result['total_time']:.2f} s")
            print(f"   Throughput: {result['requests_per_second']:.1f} req/s")
            print(f"   Avg Response Time: {result['avg_response_time']*1000:.1f} ms")
            if 'memory_usage' in result:
                print(f"   Memory Usage: {result['memory_usage']:.1f} MB")

        # Ranking: success rate high -> req/s high
        performance_data = []
        for result in results.values():
            if 'requests_per_second' in result:
                performance_data.append(
                    (f"{result['library']}({result.get('mode', 'default')})",
                     result['success_rate'],
                     result['requests_per_second'])
                )

        performance_data.sort(key=lambda x: (-x[1], -x[2]))  # success_rate desc, req/s desc
        print(f"\n🏆 Ranking (by success rate, then throughput):")
        for i, (lib, success_rate, rps) in enumerate(performance_data, 1):
            print(f"   {i}. {lib}: {rps:.1f} req/s (Success Rate: {success_rate:.1f}%)")

async def main():
    tester = PerformanceTest()
    results = await tester.run_comprehensive_test()
    if not results:
        print("❌ Benchmark failed, no results generated")
        return

    tester.print_results(results)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"rusty_req_benchmark_{timestamp}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Results saved to {filename}")

if __name__ == "__main__":
    try:
        import rusty_req
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please install: pip install rusty-req")
        exit(1)

    optional_deps = []
    try:
        import aiohttp
        optional_deps.append("aiohttp")
    except ImportError:
        print("⚠️ aiohttp not installed, skipping related benchmark")

    try:
        import httpx
        optional_deps.append("httpx")
    except ImportError:
        print("⚠️ httpx not installed, skipping related benchmark")

    try:
        import requests
        optional_deps.append("requests")
    except ImportError:
        print("⚠️ requests not installed, skipping related benchmark")

    try:
        import psutil
        optional_deps.append("psutil")
    except ImportError:
        print("⚠️ psutil not installed, skipping memory monitoring")

    if optional_deps:
        print(f"✅ Optional dependencies installed: {', '.join(optional_deps)}")

    asyncio.run(main())
