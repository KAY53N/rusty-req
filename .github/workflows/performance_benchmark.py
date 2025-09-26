name: rusty-req 性能测试

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  performance-test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v4
    
    - name: 启动 httpbin Docker 服务
      run: |
        docker run -d --name httpbin -p 8080:80 kennethreitz/httpbin:latest
        # 等待服务启动
        sleep 10
        # 验证服务是否正常运行
        curl -f http://localhost:8080/status/200
    
    - name: 设置 Python 环境
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
    
    - name: 安装依赖
      run: |
        python -m pip install --upgrade pip
        pip install rusty-req aiohttp httpx requests psutil
    
    - name: 运行性能测试
      run: python performance_test.py
      env:
        HTTPBIN_URL: http://localhost:8080
    
    - name: 停止 httpbin 服务
      run: |
        docker stop httpbin
        docker rm httpbin
