```python
import random

def is_regular_tournament(A):
    n = len(A)
    target = (n - 1) // 2
    return all(sum(A[i]) == target for i in range(n))

def random_regular_tournament_5_bruteforce():
    n = 5
    while True:
        A = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                if random.choice([True, False]):
                    A[i][j] = 1
                else:
                    A[j][i] = 1
        
        if is_regular_tournament(A):
            return A

A = random_regular_tournament_5_bruteforce()
for row in A:
    print(row)

```