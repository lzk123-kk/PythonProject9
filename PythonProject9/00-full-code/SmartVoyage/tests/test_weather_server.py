import unittest

from a2a_server import weather_server
from python_a2a import A2AClient


class TestWeatherServer(unittest.TestCase):

    def test_query(self):
        client = A2AClient("http://127.0.0.1:5005")
        result = client.ask("帮我查一下北京明天的天气")
        print(result)
        assert result