import json
import os

import pandas as pd


def generate_sft_dataset(csv_path, output_path):
    # 自动检测编码，防止中文乱码报错
    try:
        df = pd.read_csv(csv_path, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding='gbk')

    instruction = "你是一个专业的图书推荐助手。请根据提供的用户阅读历史和偏好，结合书籍的详细背景信息，撰写一段具有文学色彩且能触动读者的个性化推荐理由。"
    dataset = []

    for index, row in df.iterrows():
        # 根据你的 CSV 列名获取数据（如果列名不同请根据 csv 实际情况修改）
        title = str(row.get('title', '未知书名'))
        author = str(row.get('author', '未知作者'))
        # 假设 csv 中有 'category' 和 'info' (简介) 列
        category = str(row.get('category', '文学'))
        description = str(row.get('info', '暂无简介'))  # 豆瓣数据集通常叫 info 或 quote

        # 随机模拟历史记录
        sample_books = df.sample(2)['title'].tolist()
        history = "、《".join(sample_books)

        user_input = f"用户偏好：{category}；历史读物：《{history}》；推荐目标：《{title}》（作者：{author}）"
        user_output = f"既然你喜欢《{history}》，那么这本《{title}》一定能击中你的心。{description[:150]}"

        dataset.append({
            "instruction": instruction,
            "input": user_input,
            "output": user_output
        })

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"✅ 成功生成数据集！\n总计：{len(dataset)} 条\n保存位置：{os.path.abspath(output_path)}")


if __name__ == "__main__":
    # 👇 直接使用你刚才提供的确切路径 👇
    target_csv = r"C:\Users\26052\Desktop\doubanBook_TOP250-master\books.csv"

    if os.path.exists(target_csv):
        generate_sft_dataset(target_csv, 'book_recommend_sft.json')
    else:
        print(f"❌ 错误：在 {target_csv} 找不到文件，请确认文件是否被移动或改名。")
