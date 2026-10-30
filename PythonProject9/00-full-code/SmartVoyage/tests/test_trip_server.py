import unittest

from a2a_server import weather_server
from python_a2a import A2AClient


class TestWeatherServer(unittest.TestCase):

    def test_query(self):
        client = A2AClient("http://127.0.0.1:5007")
        result = client.ask("帮我查询成都5月1号的租车信息，成都取车，成都还车")
        print(result)
        assert result