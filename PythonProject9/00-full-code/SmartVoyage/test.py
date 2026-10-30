import requests

url = "https://k544uav444.re.qweatherapi.com/v7/weather/3d"

headers = {
    'X-QW-Api-Key': '6440fa6173384223b5cddaf32d9983c7',
    'Accept-Encoding': 'gzip, deflate, br'  # 对应 --compressed 选项，告知服务器支持压缩
}

chengdu = [
    101270101, 101270102, 101270103, 101270104, 101270105,
    101270106, 101270107, 101270108, 101270109, 101270110,
    101270111, 101270112, 101270113, 101270114, 101270115,
    101270116, 101270117, 101270118, 101270119, 101270120,
    101270121
]

beijing = [
    101010100,
    101010200,
    101010300,
    101010400,
    101010500,
    101010600,
    101010700,
    101010800,
    101010900,
    101011000,
    101011100,
    101011200,
    101011300,
    101011400,
    101011500,
    101011600,
    101011700
]


params = {
    'location': '101270101'
}

response = requests.get(url, headers=headers, params=params)

# 打印响应状态和内容
print(f"状态码: {response.status_code}")
print("响应内容:")
print(response.text)
