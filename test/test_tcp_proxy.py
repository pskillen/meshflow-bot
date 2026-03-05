import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from src.tcp_proxy import TcpProxy

class TestTcpProxy(unittest.TestCase):
    def setUp(self):
        self.proxy = TcpProxy("127.0.0.1", 4403, "127.0.0.1", 4404)

    def test_status_fields(self):
        status = self.proxy.get_status()
        self.assertIn("Offline", status)

        self.proxy.running = True
        self.proxy.target_writer = MagicMock()
        status = self.proxy.get_status()
        self.assertEqual(status["state"], "Online")
        self.assertEqual(status["clients"], 0)

    def test_remove_client(self):
        mock_writer = MagicMock()
        mock_writer.get_extra_info.return_value = ("127.0.0.1", 12345)
        
        self.proxy.clients.add(mock_writer)
        self.proxy._remove_client(mock_writer)
        
        self.assertEqual(len(self.proxy.clients), 0)
        mock_writer.close.assert_called_once()

    @patch('asyncio.start_server', new_callable=AsyncMock)
    def test_async_run_binds_server(self, mock_start_server):
        async def run_test():
            self.proxy.running = True
            
            # Cancel the watchdog and connection manager immediately to avoid hang
            async def stop_soon():
                await asyncio.sleep(0.1)
                self.proxy.running = False
            
            asyncio.create_task(stop_soon())
            await self.proxy._async_run()
            
            mock_start_server.assert_called_once()
            
        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
