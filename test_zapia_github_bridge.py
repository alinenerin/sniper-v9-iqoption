import os
from zapia_github_bridge import GitHubScanBridge

os.environ.pop('GITHUB_TOKEN', None)
os.environ.pop('GH_TOKEN', None)
try:
    GitHubScanBridge()
except ValueError as exc:
    assert str(exc) == 'GITHUB_TOKEN_REQUIRED_OUTSIDE_REPOSITORY'
else:
    raise AssertionError('token must not be optional')
print('bridge_guard=OK')
