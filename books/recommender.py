# books/recommender.py
import math
from collections import defaultdict

from .models import Rating


def get_user_cf_recommendations(target_user, top_k_users=5, top_n_items=4):
    """
    基于用户的协同过滤推荐算法 (User-CF)
    :param target_user: 当前请求推荐的目标用户对象
    :param top_k_users: 寻找多少个最相似的用户
    :param top_n_items: 最终推荐多少本书
    :return: 推荐图书的 ID 列表
    """
    # 1. 查询所有评分记录
    # 优化：只取大于等于 3 分的有效评分，避免推荐别人打低分的书
    ratings = Rating.objects.filter(score__gte=3).values('user_id', 'book_id', 'score')
    if not ratings:
        return []

    # 2. 构建 “用户 - 图书” 评分矩阵 (嵌套字典格式)
    # user_ratings = {user_id_1: {book_id_A: 5, book_id_B: 4}, user_id_2: {...}}
    user_ratings = defaultdict(dict)
    for r in ratings:
        user_ratings[r['user_id']][r['book_id']] = r['score']

    target_user_id = target_user.id

    # 【冷启动处理】如果当前用户没有任何评分记录，直接返回空
    if target_user_id not in user_ratings:
        return []

    target_items = user_ratings[target_user_id]
    similarities = {}

    # 3. 计算目标用户与其他所有用户的相似度（使用“余弦相似度”）
    for other_user_id, other_items in user_ratings.items():
        if other_user_id == target_user_id:
            continue

        # 寻找目标用户和该用户共同评分过的图书交集
        common_books = set(target_items.keys()) & set(other_items.keys())
        if not common_books:
            continue

        # 计算余弦相似度
        sum_xy = sum(target_items[book] * other_items[book] for book in common_books)
        sum_x2 = sum(target_items[book] ** 2 for book in target_items.keys())
        sum_y2 = sum(other_items[book] ** 2 for book in other_items.keys())

        if sum_x2 == 0 or sum_y2 == 0:
            sim = 0
        else:
            sim = sum_xy / (math.sqrt(sum_x2) * math.sqrt(sum_y2))

        similarities[other_user_id] = sim

    # 4. 排序获取相似度最高的前 K 个用户
    # similarities.items() 形如 [(user_id, sim_score), ...]
    sorted_sim_users = sorted(similarities.items(), key=lambda x: x[1], reverse=True)[:top_k_users]

    # 5. 根据相似用户的喜好，计算推荐图书的加权得分
    candidate_items = defaultdict(float)
    read_books = set(target_items.keys())  # 目标用户看过的书（用于排重）

    for similar_user_id, sim_score in sorted_sim_users:
        sim_user_items = user_ratings[similar_user_id]

        for book_id, score in sim_user_items.items():
            # 如果这本书目标用户还没看过
            if book_id not in read_books:
                # 推荐度 = 相似度 * 相似用户给该书的评分
                candidate_items[book_id] += sim_score * score

    # 6. 对候选图书按推荐度降序排列，截取前 N 本
    sorted_candidates = sorted(candidate_items.items(), key=lambda x: x[1], reverse=True)[:top_n_items]

    # 提取图书的 ID 并返回
    recommend_book_ids = [item[0] for item in sorted_candidates]
    return recommend_book_ids
