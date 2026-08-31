"""Audit sandbox network denial loaded automatically by Python."""
import socket

class AuditNetworkDenied(PermissionError):
    pass

def _deny(*args, **kwargs):
    raise AuditNetworkDenied("audit sandbox denies DNS and network access")

class DeniedSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        raise AuditNetworkDenied("audit sandbox denies socket creation")

socket.socket = DeniedSocket
socket.create_connection = _deny
socket.getaddrinfo = _deny
socket.gethostbyname = _deny
socket.gethostbyname_ex = _deny
socket.gethostbyaddr = _deny
