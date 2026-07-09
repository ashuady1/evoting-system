"""
security/isolation_forest.py

Isolation Forest, implemented from scratch, following Liu, Ting & Zhou
(2008) — no scikit-learn. The core idea: anomalies are "few and
different," so they get isolated by random splits faster (shorter path
from root to leaf) than normal points sitting in a dense cluster.

Building one tree:
  - Pick a random feature, pick a random split value between that
    feature's min and max in the current data, split, recurse.
  - Stop when a node has 1 point left, or we hit the height limit.

Anomaly score for a point x:
  - Average its path length across all trees in the forest, E(h(x)).
  - Normalize against c(n): the average path length of an unsuccessful
    search in a Binary Search Tree of n nodes — this makes scores
    comparable across different sample sizes.
  - s(x, n) = 2^(-E(h(x)) / c(n))
  - s -> 1: likely anomaly (isolated fast). s < 0.5: likely normal.
"""

import math
import random


def _c(n: int) -> float:
    """Average path length of an unsuccessful BST search over n points —
    used both as the leaf-node correction term and as the normalizer."""
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    harmonic_approx = math.log(n - 1) + 0.5772156649  # Euler-Mascheroni constant
    return 2 * harmonic_approx - (2 * (n - 1) / n)


class _ExternalNode:
    __slots__ = ("size",)

    def __init__(self, size):
        self.size = size


class _InternalNode:
    __slots__ = ("feature", "split_value", "left", "right")

    def __init__(self, feature, split_value, left, right):
        self.feature = feature
        self.split_value = split_value
        self.left = left
        self.right = right


def _build_tree(data, current_height, height_limit):
    n = len(data)
    if current_height >= height_limit or n <= 1:
        return _ExternalNode(n)

    num_features = len(data[0])
    feature_order = list(range(num_features))
    random.shuffle(feature_order)

    # Pick the first feature (in random order) that actually varies in
    # this subset — a constant feature can't produce a useful split.
    chosen_feature, lo, hi = None, None, None
    for f in feature_order:
        values = [row[f] for row in data]
        f_lo, f_hi = min(values), max(values)
        if f_hi > f_lo:
            chosen_feature, lo, hi = f, f_lo, f_hi
            break

    if chosen_feature is None:
        return _ExternalNode(n)  # every feature is constant here — can't split further

    split_value = random.uniform(lo, hi)
    left = [row for row in data if row[chosen_feature] < split_value]
    right = [row for row in data if row[chosen_feature] >= split_value]

    if not left or not right:
        return _ExternalNode(n)  # rare float-boundary edge case

    return _InternalNode(
        chosen_feature, split_value,
        _build_tree(left, current_height + 1, height_limit),
        _build_tree(right, current_height + 1, height_limit),
    )


def _path_length(x, node, current_height):
    if isinstance(node, _ExternalNode):
        return current_height + _c(node.size)
    if x[node.feature] < node.split_value:
        return _path_length(x, node.left, current_height + 1)
    return _path_length(x, node.right, current_height + 1)


class IsolationForest:
    def __init__(self, n_trees: int = 100, subsample_size: int = 256):
        self.n_trees = n_trees
        self.subsample_size = subsample_size
        self.trees = []
        self._effective_subsample_size = None

    def fit(self, data: list):
        n = len(data)
        self._effective_subsample_size = min(self.subsample_size, n)
        height_limit = math.ceil(math.log2(max(self._effective_subsample_size, 2)))

        self.trees = []
        for _ in range(self.n_trees):
            sample = random.sample(data, self._effective_subsample_size)
            self.trees.append(_build_tree(sample, 0, height_limit))
        return self

    def anomaly_score(self, x) -> float:
        avg_path_length = sum(_path_length(x, tree, 0) for tree in self.trees) / len(self.trees)
        normalizer = _c(self._effective_subsample_size)
        if normalizer == 0:
            return 0.0
        return 2 ** (-avg_path_length / normalizer)

    def score_all(self, data: list) -> list:
        return [self.anomaly_score(x) for x in data]


if __name__ == "__main__":
    random.seed(42)  # reproducible self-test

    print("--- Synthetic test: a tight normal cluster plus a few obvious outliers ---")
    normal_points = [[random.gauss(0, 1), random.gauss(0, 1)] for _ in range(200)]
    outlier_points = [[20, 20], [-18, 22], [25, -19], [0, 30]]
    dataset = normal_points + outlier_points

    forest = IsolationForest(n_trees=150, subsample_size=128)
    forest.fit(dataset)
    scores = forest.score_all(dataset)

    normal_scores = scores[:len(normal_points)]
    outlier_scores = scores[len(normal_points):]

    avg_normal = sum(normal_scores) / len(normal_scores)
    avg_outlier = sum(outlier_scores) / len(outlier_scores)
    print(f"Average anomaly score — normal points: {avg_normal:.3f}")
    print(f"Average anomaly score — outlier points: {avg_outlier:.3f}")
    check1 = avg_outlier > avg_normal + 0.15
    print(f"[{'PASS' if check1 else 'FAIL'}] outliers score meaningfully higher than normal points")

    # Rank everything and confirm the 4 known outliers land at (or very
    # near) the very top of the ranking.
    ranked = sorted(range(len(dataset)), key=lambda i: -scores[i])
    top_4_indices = set(ranked[:4])
    outlier_indices = set(range(len(normal_points), len(dataset)))
    overlap = len(top_4_indices & outlier_indices)
    print(f"[{'PASS' if overlap >= 3 else 'FAIL'}] {overlap}/4 known outliers are in the top 4 highest-scored points")

    all_passed = check1 and overlap >= 3
    print("\nALL TESTS PASSED" if all_passed else "\nSOME TESTS FAILED")
