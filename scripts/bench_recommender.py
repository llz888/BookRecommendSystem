"""推荐算法压测：对比原始实现与 numpy 向量化实现的耗时。

用法：
    .venv/bin/python scripts/bench_recommender.py

脚本使用内存中的合成数据，不读写数据库。
"""

import math
import random
import statistics
import time
from collections import defaultdict


def legacy_cf(rows, target_user_id, top_k_users=5, top_n_items=4):
    """优化前的实现（逐用户计算相似度）。"""
    user_ratings = defaultdict(dict)
    for uid, bid, score in rows:
        user_ratings[uid][bid] = score
    if target_user_id not in user_ratings:
        return []

    target_items = user_ratings[target_user_id]
    similarities = {}
    for other_id, other_items in user_ratings.items():
        if other_id == target_user_id:
            continue
        common = set(target_items) & set(other_items)
        if not common:
            continue
        sum_xy = sum(target_items[b] * other_items[b] for b in common)
        sum_x2 = sum(v ** 2 for v in target_items.values())
        sum_y2 = sum(v ** 2 for v in other_items.values())
        similarities[other_id] = sum_xy / (math.sqrt(sum_x2) * math.sqrt(sum_y2))

    top = sorted(similarities.items(), key=lambda x: x[1], reverse=True)[:top_k_users]
    candidate = defaultdict(float)
    seen = set(target_items)
    for uid, sim in top:
        for bid, score in user_ratings[uid].items():
            if bid not in seen:
                candidate[bid] += sim * score
    ranked = sorted(candidate.items(), key=lambda x: x[1], reverse=True)[:top_n_items]
    return [bid for bid, _ in ranked]


def build_rows(n_clusters=50, users_per_cluster=400, books_per_cluster=100, ratings_per_user=20, seed=42):
    """构造带聚类的评分数据：同一簇的用户偏好同一批书。"""
    rng = random.Random(seed)
    rows = []
    for cluster in range(n_clusters):
        book_pool = [cluster * books_per_cluster + i for i in range(books_per_cluster)]
        for u in range(users_per_cluster):
            uid = cluster * users_per_cluster + u
            for bid in rng.sample(book_pool, ratings_per_user):
                rows.append((uid, bid, rng.randint(3, 5)))
    return rows


def timeit(func, *args, repeat=3):
    durations = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = func(*args)
        durations.append(time.perf_counter() - start)
    return statistics.median(durations), result


def main():
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    import django
    django.setup()

    rows = build_rows()
    target = 0
    print(f"数据规模：{len(rows)} 条评分，"
          f"{len({r[0] for r in rows})} 个用户，{len({r[1] for r in rows})} 本书")

    from books.recommender import build_index, recommend_from_index, recommend_from_ratings  # noqa: E402

    index = build_index(rows)

    legacy_time, legacy_result = timeit(legacy_cf, rows, target)
    cold_time, _ = timeit(recommend_from_ratings, rows, target)
    warm_time, new_result = timeit(recommend_from_index, index, target)

    print(f"原始实现（每次重建）：{legacy_time * 1000:8.1f} ms")
    print(f"新实现（首次构建）：{cold_time * 1000:8.1f} ms")
    print(f"新实现（命中缓存）：{warm_time * 1000:8.1f} ms")
    print(f"缓存命中加速比：{legacy_time / warm_time:.1f}x")
    print(f"结果一致：{legacy_result == new_result} | {new_result}")


if __name__ == "__main__":
    main()
