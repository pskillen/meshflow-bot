import unittest
from unittest.mock import MagicMock, patch
import threading
import time
import socket
from src.tcp_proxy import TcpProxy

class TestTcpProxy(unittest.TestCase):
    def setUp(self):
        self.proxy = TcpProxy("127.0.0.1", 4403, "127.0.0.1", 4404)

    def test_lock_is_rlock(self):
        # threading.RLock() might be a factory function returning a platform-specific class
        self.assertTrue(hasattr(self.proxy.lock, 'acquire') and hasattr(self.proxy.lock, '_count') or isinstance(self.proxy.lock, type(threading.RLock())))

    def test_remove_client_no_deadlock(self):
        # Mock a client socket
        mock_client = MagicMock()
        mock_client.getpeername.return_value = ("127.0.0.1", 12345)
        
        self.proxy.clients.append(mock_client)
        
        # This should not deadlock now
        self.proxy._remove_client(mock_client)
        
        self.assertEqual(len(self.proxy.clients), 0)
        mock_client.close.assert_called_once()

    def test_process_radio_data_deadlock_fix(self):
        # This test simulates the exact deadlock condition:
        # _process_radio_data holds the lock and calls _remove_client (via sendall failure)
        # which tries to acquire the lock again.
        
        mock_client = MagicMock()
        mock_client.getpeername.return_value = ("127.0.0.1", 12345)
        # Force sendall to fail
        mock_client.sendall.side_effect = Exception("Broken pipe")
        
        self.proxy.clients.append(mock_client)
        
        # Valid Meshtastic packet header \x94\xc3 + length 0001 + 1 byte data
        packet_data = b'\x94\xc3\x00\x01\x00'
        
        # This call should not hang
        self.proxy._process_radio_data(packet_data)
        
        # Verify client was removed
        self.assertEqual(len(self.proxy.clients), 0)
        mock_client.close.assert_called_once()

    def test_get_status_thread_safety(self):
        # Ensure get_status can be called while holding the lock elsewhere
        self.proxy.running = True
        self.proxy.target_socket = MagicMock() # To make it look "Online"
        with self.proxy.lock:
            status = self.proxy.get_status()
            self.assertEqual(status["state"], "Online")

    @patch('socket.socket')
    def test_client_socket_has_timeout(self, mock_socket_class):
        # Mock the server socket instance
        mock_server_sock = MagicMock()
        mock_socket_class.return_value = mock_server_sock
        
        # Mock accept() to return a mock client socket
        mock_client = MagicMock()
        mock_server_sock.accept.return_value = (mock_client, ("1.2.3.4", 5555))
        
        # We need to mock select.select to return the server_socket as readable
        with patch('select.select') as mock_select:
            # First call: return server socket as readable
            # Second call: flip self.running to False to exit loop
            def select_side_effect(*args, **kwargs):
                if self.proxy.running:
                    self.proxy.running = False
                    return ([mock_server_sock], [], [])
                return ([], [], [])
            
            mock_select.side_effect = select_side_effect
            
            self.proxy.running = True
            self.proxy.target_socket = MagicMock() # Avoid reconnect logic
            self.proxy._run()
            
        # Verify timeout was set on the client socket
        mock_client.settimeout.assert_called_with(10.0)

if __name__ == "__main__":
    unittest.main()
