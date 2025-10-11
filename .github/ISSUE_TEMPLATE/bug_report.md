---
name: Bug report
about: Create a report to help us improve
title: "[Bug] Memory leak in [component] when handling [scenario]"
labels: ''
assignees: ''

---

**Bug Description**
A clear and concise description of the bug.

**Steps to Reproduce**
Steps to reproduce the behavior:
1. 
2. 
3. 

**Expected Behavior**
A clear description of what you expected to happen.

**Actual Behavior**
A description of what actually happened.

**Environment Information**
- OS: [e.g. Windows 11, Ubuntu 22.04, macOS Ventura]
- Python Version: [e.g. Python 3.9, 3.10, 3.11]
- Rusty-req Version: [e.g. 0.1.0]
- Dependency Versions: [e.g. requests, aiohttp, etc.]

**Code Example**
```python
import rusty_req

# Minimal code example to reproduce the issue
client = rusty_req.Client()
response = client.get("https://api.example.com/data")
print(response.text)
