import csv
import os
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from books.models import Book, Rating
from django.conf import settings


class Command(BaseCommand):
    help = '批量导入GitHub数据集图书并自动抓取豆瓣评价'

    def handle(self, *args, **options):
        # 1. 导入图书基本信息
        csv_path = os.path.join(settings.BASE_DIR, 'books.csv')
        self.stdout.write(f"正在从 {csv_path} 导入图书...")

        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            book_count = 0
            for row in reader:
                # 对应你的模型字段：title, author, isbn, category, description, pic_url
                book, created = Book.objects.update_or_create(
                    isbn=row['isbn'],
                    defaults={
                        'title': row['title'],
                        'author': row['author'],
                        'category': row['category'],
                        'description': row['description'],
                        'pic_url': row['pic_url']  # 存储相对路径，如 book_covers/1007305.jpg
                    }
                )
                book_count += 1
            self.stdout.write(self.style.SUCCESS(f"成功导入/更新 {book_count} 本图书"))

        # 2. 批量抓取并导入评价 (利用爬虫助手用户)
        robot_user, _ = User.objects.get_or_create(username='豆瓣助手', defaults={'is_staff': True})
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.116'}

        all_books = Book.objects.all()
        for book in all_books:
            # 使用ISBN作为豆瓣书籍号构造URL
            url = f'https://book.douban.com/subject/{book.isbn}/blockquotes'
            try:
                r = requests.get(url, headers=headers, timeout=5)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, 'html.parser')
                    items = soup.find('div', class_="blockquote-list").find('ul').findAll('li')
                    for item in items:
                        content = item.find('figure').text.strip()
                        Rating.objects.get_or_create(
                            user=robot_user,
                            book=book,
                            comment=content[:500],
                            defaults={'score': 5}
                        )
                    self.stdout.write(f"《{book.title}》评价导入成功")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"跳过《{book.title}》: {e}"))
