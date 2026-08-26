from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field
from typing import Protocol


class Keychain(Protocol):
    def set(self, account: str, value: str) -> None: ...

    def get(self, account: str) -> str | None: ...

    def delete(self, account: str) -> None: ...


class NativeKeychain(Protocol):
    def set(self, service: str, account: str, value: str) -> None: ...

    def get(self, service: str, account: str) -> str | None: ...

    def delete(self, service: str, account: str) -> None: ...


@dataclass
class InMemoryKeychain:
    values: dict[str, str] = field(default_factory=dict)

    def set(self, account: str, value: str) -> None:
        self.values[account] = value

    def get(self, account: str) -> str | None:
        return self.values.get(account)

    def delete(self, account: str) -> None:
        self.values.pop(account, None)


class MacOSSecurityFramework:
    _UTF8 = 0x08000100
    _SUCCESS = 0
    _DUPLICATE_ITEM = -25299
    _ITEM_NOT_FOUND = -25300

    def __init__(self) -> None:
        if sys.platform != "darwin":
            msg = "macOS Keychain is unavailable on this platform"
            raise RuntimeError(msg)
        self._security = ctypes.CDLL(
            "/System/Library/Frameworks/Security.framework/Security",
        )
        self._core = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
        )
        self._configure_functions()

    def _configure_functions(self) -> None:
        self._core.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        self._core.CFStringCreateWithCString.restype = ctypes.c_void_p
        self._core.CFDataCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_long,
        ]
        self._core.CFDataCreate.restype = ctypes.c_void_p
        self._core.CFDictionaryCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._core.CFDictionaryCreate.restype = ctypes.c_void_p
        self._core.CFDataGetLength.argtypes = [ctypes.c_void_p]
        self._core.CFDataGetLength.restype = ctypes.c_long
        self._core.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        self._core.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_ubyte)
        self._core.CFRelease.argtypes = [ctypes.c_void_p]
        self._core.CFRelease.restype = None
        self._security.SecItemAdd.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._security.SecItemAdd.restype = ctypes.c_int32
        self._security.SecItemUpdate.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._security.SecItemUpdate.restype = ctypes.c_int32
        self._security.SecItemCopyMatching.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._security.SecItemCopyMatching.restype = ctypes.c_int32
        self._security.SecItemDelete.argtypes = [ctypes.c_void_p]
        self._security.SecItemDelete.restype = ctypes.c_int32

    def _constant(self, library: ctypes.CDLL, name: str) -> int:
        value = ctypes.c_void_p.in_dll(library, name).value
        if value is None:
            msg = f"macOS framework constant unavailable: {name}"
            raise RuntimeError(msg)
        return value

    def _string(self, value: str) -> int:
        pointer = self._core.CFStringCreateWithCString(
            None,
            value.encode("utf-8"),
            self._UTF8,
        )
        if not pointer:
            msg = "Could not allocate Keychain string"
            raise RuntimeError(msg)
        return int(pointer)

    def _data(self, value: bytes) -> int:
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        pointer = self._core.CFDataCreate(None, buffer, len(value))
        if not pointer:
            msg = "Could not allocate Keychain data"
            raise RuntimeError(msg)
        return int(pointer)

    def _dictionary(self, pairs: list[tuple[int, int]]) -> int:
        keys = (ctypes.c_void_p * len(pairs))(*(key for key, _ in pairs))
        values = (ctypes.c_void_p * len(pairs))(*(value for _, value in pairs))
        pointer = self._core.CFDictionaryCreate(
            None,
            keys,
            values,
            len(pairs),
            None,
            None,
        )
        if not pointer:
            msg = "Could not allocate Keychain query"
            raise RuntimeError(msg)
        return int(pointer)

    def _base_query(self, service: str, account: str) -> tuple[int, list[int]]:
        service_value = self._string(service)
        account_value = self._string(account)
        query = self._dictionary(
            [
                (
                    self._constant(self._security, "kSecClass"),
                    self._constant(self._security, "kSecClassGenericPassword"),
                ),
                (self._constant(self._security, "kSecAttrService"), service_value),
                (self._constant(self._security, "kSecAttrAccount"), account_value),
            ],
        )
        return query, [service_value, account_value]

    def _release_all(self, values: list[int]) -> None:
        for value in values:
            self._core.CFRelease(value)

    def set(self, service: str, account: str, value: str) -> None:
        query, owned = self._base_query(service, account)
        value_data = self._data(value.encode("utf-8"))
        add_query = self._dictionary(
            [
                (
                    self._constant(self._security, "kSecClass"),
                    self._constant(self._security, "kSecClassGenericPassword"),
                ),
                (self._constant(self._security, "kSecAttrService"), owned[0]),
                (self._constant(self._security, "kSecAttrAccount"), owned[1]),
                (self._constant(self._security, "kSecValueData"), value_data),
            ],
        )
        try:
            status = int(self._security.SecItemAdd(add_query, None))
            if status == self._DUPLICATE_ITEM:
                attributes = self._dictionary(
                    [(self._constant(self._security, "kSecValueData"), value_data)],
                )
                try:
                    status = int(self._security.SecItemUpdate(query, attributes))
                finally:
                    self._core.CFRelease(attributes)
            if status != self._SUCCESS:
                msg = f"macOS Keychain write failed with OSStatus {status}"
                raise RuntimeError(msg)
        finally:
            self._core.CFRelease(add_query)
            self._core.CFRelease(query)
            self._core.CFRelease(value_data)
            self._release_all(owned)

    def get(self, service: str, account: str) -> str | None:
        query, owned = self._base_query(service, account)
        get_query = self._dictionary(
            [
                (
                    self._constant(self._security, "kSecClass"),
                    self._constant(self._security, "kSecClassGenericPassword"),
                ),
                (self._constant(self._security, "kSecAttrService"), owned[0]),
                (self._constant(self._security, "kSecAttrAccount"), owned[1]),
                (
                    self._constant(self._security, "kSecReturnData"),
                    self._constant(self._core, "kCFBooleanTrue"),
                ),
                (
                    self._constant(self._security, "kSecMatchLimit"),
                    self._constant(self._security, "kSecMatchLimitOne"),
                ),
            ],
        )
        result = ctypes.c_void_p()
        try:
            status = int(self._security.SecItemCopyMatching(get_query, ctypes.byref(result)))
            if status == self._ITEM_NOT_FOUND:
                return None
            if status != self._SUCCESS or result.value is None:
                msg = f"macOS Keychain read failed with OSStatus {status}"
                raise RuntimeError(msg)
            length = int(self._core.CFDataGetLength(result.value))
            pointer = self._core.CFDataGetBytePtr(result.value)
            return ctypes.string_at(pointer, length).decode("utf-8")
        finally:
            if result.value is not None:
                self._core.CFRelease(result.value)
            self._core.CFRelease(get_query)
            self._core.CFRelease(query)
            self._release_all(owned)

    def delete(self, service: str, account: str) -> None:
        query, owned = self._base_query(service, account)
        try:
            status = int(self._security.SecItemDelete(query))
            if status not in {self._SUCCESS, self._ITEM_NOT_FOUND}:
                msg = f"macOS Keychain delete failed with OSStatus {status}"
                raise RuntimeError(msg)
        finally:
            self._core.CFRelease(query)
            self._release_all(owned)


@dataclass(frozen=True)
class MacOSSecurityKeychain:
    service: str = "starklabs-model-evals"
    backend: NativeKeychain | None = None

    def _backend(self) -> NativeKeychain:
        return self.backend or MacOSSecurityFramework()

    def set(self, account: str, value: str) -> None:
        self._backend().set(self.service, account, value)

    def get(self, account: str) -> str | None:
        return self._backend().get(self.service, account)

    def delete(self, account: str) -> None:
        self._backend().delete(self.service, account)
