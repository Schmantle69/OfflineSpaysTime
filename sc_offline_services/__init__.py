"""Descriptor-driven gRPC emulator for the Star Citizen client's external services.

Serves ConfigService, InstanceManagerService and PushService from JSON fixtures and
proxies every other method in the loaded descriptor set to the real StarBackend.
"""

from .descriptors import DescriptorSet, MethodInfo
from .fixtures import Fixtures
from .server import Emulator, ServerConfig

__all__ = ["DescriptorSet", "MethodInfo", "Fixtures", "Emulator", "ServerConfig"]
