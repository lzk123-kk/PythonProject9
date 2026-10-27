"""
MCP 服务器测试模块

测试内容：
1. 格式编码工具（纯函数测试，零依赖）
2. MCP 服务器集成测试（需要数据库连接）

运行方式：
    cd SmartVoyage
    python -m tests.test_mcp_servers
"""

import unittest
import json
import sys
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

# 确保能导入 SmartVoyage 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ==================== 1. 格式编码工具测试（纯函数，零依赖） ====================
class TestFormatEncoder(unittest.TestCase):
    """测试 default_encoder 函数和 DateEncoder 类"""

    def setUp(self):
        from utils.format import default_encoder, DateEncoder
        self.default_encoder_func = default_encoder
        self.date_encoder_cls = DateEncoder

    def test_encode_datetime(self):
        """测试 datetime 编码"""
        dt = datetime(2025, 7, 30, 14, 30, 0)
        result = self.default_encoder_func(dt)
        self.assertEqual(result, '2025-07-30 14:30:00')

    def test_encode_date(self):
        """测试 date 编码"""
        d = date(2025, 7, 30)
        result = self.default_encoder_func(d)
        self.assertEqual(result, '2025-07-30')

    def test_encode_timedelta(self):
        """测试 timedelta 编码"""
        td = timedelta(hours=5, minutes=30)
        result = self.default_encoder_func(td)
        self.assertEqual(result, '5:30:00')

    def test_encode_decimal(self):
        """测试 Decimal 编码"""
        dec = Decimal('123.45')
        result = self.default_encoder_func(dec)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 123.45)

    def test_encode_unknown(self):
        """测试未知类型原样返回"""
        obj = "hello"
        result = self.default_encoder_func(obj)
        self.assertEqual(result, "hello")

    def test_date_encoder_json_dumps(self):
        """测试 DateEncoder 类与 json.dumps 配合使用"""
        data = {
            "date": date(2025, 7, 30),
            "datetime": datetime(2025, 7, 30, 14, 30, 0),
            "value": Decimal('99.99')
        }
        result = json.dumps(data, cls=self.date_encoder_cls)
        parsed = json.loads(result)
        self.assertEqual(parsed["date"], "2025-07-30")
        self.assertEqual(parsed["datetime"], "2025-07-30 14:30:00")
        self.assertEqual(parsed["value"], 99.99)


# ==================== 2. MCP 服务器集成测试（需要数据库） ====================

class TestWeatherMCPIntegration(unittest.TestCase):
    """集成测试：天气 MCP 服务器"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_weather_server import WeatherService
        cls.service = WeatherService()

    def test_query_weather_single_day(self):
        """测试单天天气查询——北京 2026-04-29"""
        result = self.service.query_weather("北京", "2026-04-29", "2026-04-29")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["city"], "北京")
        self.assertEqual(first["fx_date"], "2026-04-29")

    def test_query_weather_date_range(self):
        """测试日期范围天气查询——北京 2026-04-29 ~ 2026-05-03"""
        result = self.service.query_weather("北京", "2026-04-29", "2026-05-03")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(len(parsed["data"]), 5)
        for day in parsed["data"]:
            self.assertGreaterEqual(day["fx_date"], "2026-04-29")
            self.assertLessEqual(day["fx_date"], "2026-05-03")

    def test_query_weather_chengdu(self):
        """测试成都天气查询"""
        result = self.service.query_weather("成都", "2026-05-01", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        self.assertEqual(parsed["data"][0]["city"], "成都")

    def test_query_weather_no_data(self):
        """测试无数据情况"""
        result = self.service.query_weather("火星", "2026-05-01", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    # def test_weather_mcp_server_config(self):
    #     """验证天气 MCP 服务器配置"""
    #     from SmartVoyage.mcp_server.mcp_weather_server import create_weather_mcp_server
    #     server = create_weather_mcp_server()
    #     self.assertEqual(server.name, "WeatherTools")


class TestTicketMCPIntegration(unittest.TestCase):
    """集成测试：票务 MCP 服务器"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_ticket_server import TicketService
        cls.service = TicketService()

    def test_query_train(self):
        """测试火车票查询——北京到成都 2026-05-01"""
        result = self.service.query_train("北京", "成都", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["departure_city"], "北京")
        self.assertEqual(first["arrival_city"], "成都")
        self.assertIn("train_number", first)

    def test_query_train_with_seat(self):
        """测试带座位类型的火车票查询——北京到成都 二等座"""
        result = self.service.query_train("北京", "成都", "2026-05-01", "二等座")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        for item in parsed["data"]:
            self.assertEqual(item["seat_type"], "二等座")

    def test_query_train_no_data(self):
        """测试无数据情况——北京到上海无数据"""
        result = self.service.query_train("北京", "上海", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_query_flight(self):
        """测试机票查询——北京到成都 2026-05-01"""
        result = self.service.query_flight("北京", "成都", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["departure_city"], "北京")
        self.assertEqual(first["arrival_city"], "成都")

    def test_query_flight_with_cabin(self):
        """测试带舱位类型的机票查询——头等舱"""
        result = self.service.query_flight("北京", "成都", "2026-05-01", "头等舱")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        for item in parsed["data"]:
            self.assertEqual(item["cabin_type"], "头等舱")

    def test_query_concert(self):
        """测试演唱会票查询——薛之谦 成都 2026-05-01"""
        result = self.service.query_concert("成都", "薛之谦", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["artist"], "薛之谦")
        self.assertEqual(first["city"], "成都")
        self.assertEqual(first["venue"], "成都东安湖体育公园主体育场")

    def test_query_concert_dengzaiqi(self):
        """测试演唱会票查询——邓紫棋 成都"""
        result = self.service.query_concert("成都", "邓紫棋", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        self.assertEqual(parsed["data"][0]["venue"], "凤凰山体育公园综合体育馆")

    def test_query_concert_no_data(self):
        """测试无数据情况——不存在的艺人"""
        result = self.service.query_concert("成都", "周杰伦", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    # def test_ticket_mcp_server_config(self):
    #     """验证票务 MCP 服务器配置"""
    #     from SmartVoyage.mcp_server.mcp_ticket_server import create_ticket_mcp_server
    #     server = create_ticket_mcp_server()
    #     self.assertEqual(server.name, "TicketTools")


class TestTripMCPIntegration(unittest.TestCase):
    """集成测试：行程 MCP 服务器"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_trip_server import TripService
        cls.service = TripService()

    def test_query_car_rental(self):
        """测试租车查询——成都 2026-05-01"""
        result = self.service.query_car_rental("成都", "成都", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        self.assertEqual(first["pickup_city"], "成都")
        self.assertEqual(first["return_city"], "成都")

    def test_query_car_rental_with_type(self):
        """测试带车型的租车查询——SUV"""
        result = self.service.query_car_rental("成都", "成都", "2026-05-01", "SUV")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        for item in parsed["data"]:
            self.assertEqual(item["car_type"], "SUV")

    def test_query_car_rental_no_data(self):
        """测试无数据情况——北京无租车数据"""
        result = self.service.query_car_rental("北京", "北京", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_query_insurance(self):
        """测试保险查询（全部）"""
        result = self.service.query_insurance()
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)

    def test_query_insurance_with_type(self):
        """测试带类型的保险查询——综合型"""
        result = self.service.query_insurance("综合型")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        for item in parsed["data"]:
            self.assertEqual(item["insurance_type"], "综合型")

    def test_query_insurance_jingwai(self):
        """测试境外型保险查询"""
        result = self.service.query_insurance("境外型")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        for item in parsed["data"]:
            self.assertEqual(item["insurance_type"], "境外型")

    # def test_trip_mcp_server_config(self):
    #     """验证行程 MCP 服务器配置"""
    #     from SmartVoyage.mcp_server.mcp_trip_server import create_trip_mcp_server
    #     server = create_trip_mcp_server()
    #     self.assertEqual(server.name, "TripTools")


if __name__ == "__main__":
    unittest.main(verbosity=2)