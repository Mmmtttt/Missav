from __future__ import annotations

import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


protocol = types.ModuleType("protocol")
base = types.ModuleType("protocol.base")
runtime_config = types.ModuleType("protocol.runtime_config")
base.ProtocolProvider = object
runtime_config.ProtocolConfigStore = type(
    "ProtocolConfigStore",
    (),
    {"get_plugin_config": lambda self, _name, reload=False: {}},
)
protocol.base = base
protocol.runtime_config = runtime_config
sys.modules.setdefault("protocol", protocol)
sys.modules.setdefault("protocol.base", base)
sys.modules.setdefault("protocol.runtime_config", runtime_config)
