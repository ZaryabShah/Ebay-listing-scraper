import requests

url = "https://www.facebook.com/CokePakistan/"

querystring = {"brand_redir":"1374953566137551"}

payload = ""
headers = {
    # "cookie": "sb=amNbaMBg2shVR8K6A4P0F49Z",
    "User-Agent": "insomnia/11.2.0"
}

response = requests.request("GET", url, data=payload, headers=headers, params=querystring)
with open("response.html", "w", encoding="utf-8") as file:
    file.write(response.text)
print(response.text)