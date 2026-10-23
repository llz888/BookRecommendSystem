import requests
from bs4 import BeautifulSoup
import csv
import os
import time

# === 1. 配置路径（确保指向你的 Django 项目 media 目录） ===
# 如果脚本在项目根目录运行，使用这个相对路径
current_path = os.getcwd()
SAVE_DIR = os.path.join(current_path, 'media', 'book_covers')
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)
    print(f"创建文件夹成功: {SAVE_DIR}")
# 伪装浏览器，防止被封
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}


def download_image(url, filename):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://book.douban.com/'  # 必须加上这个，告诉豆瓣我们从哪来的
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            file_path = os.path.join(SAVE_DIR, filename)
            with open(file_path, 'wb') as f:
                f.write(r.content)
            # 检查文件是否真的产生了
            if os.path.exists(file_path):
                return True
        else:
            print(f"下载失败，状态码: {r.status_code}，链接: {url}")
    except Exception as e:
        print(f"下载异常: {e}")
    return False


# 存储抓取结果
all_books = []

print("开始抓取豆瓣图书 Top250...")

for i in range(0, 3):  # 先抓取前 3 页（75本）做测试，成功后再改为 10
    url = f'https://book.douban.com/top250?start={i * 25}'
    try:
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.findAll('table', width="100%")

        for item in items:
            # 提取基础信息
            title = item.find_all('a')[1].get('title')
            info = item.find('p', class_='pl').text
            # 简单的作者提取：取第一个斜杠前的内容
            author = info.split('/')[0].strip()

            # 提取图片 URL
            img_tag = item.find('img')
            remote_img_url = img_tag.get('src') if img_tag else ""

            # 提取豆瓣 ID 作为临时 ISBN (因为 Top250 列表页没有直接显示 ISBN)
            book_id = item.find('a').get('href').split('/')[-2]

            # 下载图片到本地
            img_filename = f"{book_id}.jpg"
            if remote_img_url:
                print(f"正在下载: 《{title}》的封面...")
                download_image(remote_img_url, img_filename)
                time.sleep(0.5)  # 稍微停顿，防止被封IP

            # 构建符合你系统格式的数据
            book_data = {
                'title': title,
                'author': author,
                'isbn': book_id,  # 毕设演示可以用豆瓣ID充当ISBN
                'category': '文学',  # 默认分类，后续可在后台改
                'description': info,
                'pic_url': f"book_covers/{img_filename}"  # 存入数据库的相对路径
            }
            all_books.append(book_data)

    except Exception as e:
        print(f"抓取第 {i} 页出错: {e}")

# === 2. 保存为标准 CSV 文件 ===
csv_file = 'books.csv'
with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
    fieldnames = ['title', 'author', 'isbn', 'category', 'description', 'pic_url']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(all_books)

print(f"\n🎉 抓取完成！共获取 {len(all_books)} 本图书数据。")
print(f"数据已保存至: {csv_file}")
print(f"图片已保存至: {SAVE_DIR}")
