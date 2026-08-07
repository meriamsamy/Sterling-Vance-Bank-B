# Retrieval Evaluation Results

## Detailed Results

| Architecture | Question ID | Category   | Correct | Latency (s) | Tokens | Documents | Iterations | Status   |
| :----------- | ----------: | :--------- | :------ | ----------: | -----: | --------: | ---------: | :------- |
| Naive RAG    |           1 | General    | True    |       4.329 |   3220 |         3 |          1 | VERIFIED |
| Naive RAG    |           2 | General    | True    |      11.007 |   6497 |         3 |          1 | VERIFIED |
| Naive RAG    |           3 | Identifier | True    |       39.94 |   4794 |         3 |          1 | VERIFIED |
| Naive RAG    |           4 | Identifier | False   |      50.027 |   5707 |         3 |          1 | VERIFIED |
| Naive RAG    |           5 | Multi-hop  | True    |      33.151 |   4417 |         3 |          1 | VERIFIED |
| Naive RAG    |           6 | Multi-hop  | False   |      41.067 |   5510 |         3 |          1 | VERIFIED |
| Hybrid RAG   |           1 | General    | True    |      20.871 |   2799 |         1 |          1 | VERIFIED |
| Hybrid RAG   |           2 | General    | True    |      36.377 |   5229 |         3 |          1 | VERIFIED |
| Hybrid RAG   |           3 | Identifier | True    |      29.937 |   3432 |         1 |          1 | VERIFIED |
| Hybrid RAG   |           4 | Identifier | True    |      34.881 |   4799 |         1 |          1 | VERIFIED |
| Hybrid RAG   |           5 | Multi-hop  | False   |      30.533 |   4352 |         1 |          1 | VERIFIED |
| Hybrid RAG   |           6 | Multi-hop  | False   |      29.262 |   3819 |         1 |          1 | VERIFIED |
| Agentic RAG  |           1 | General    | True    |      21.554 |   2568 |         1 |          2 | VERIFIED |
| Agentic RAG  |           2 | General    | True    |      33.576 |   5033 |         4 |          2 | VERIFIED |
| Agentic RAG  |           3 | Identifier | True    |      42.495 |   5389 |         1 |          2 | VERIFIED |
| Agentic RAG  |           4 | Identifier | True    |      49.447 |   6910 |         8 |          2 | VERIFIED |
| Agentic RAG  |           5 | Multi-hop  | False   |      64.361 |   7881 |        10 |          2 | VERIFIED |
| Agentic RAG  |           6 | Multi-hop  | False   |      50.913 |   6928 |         8 |          2 | VERIFIED |

## Summary

| Architecture | Accuracy | AvgTokens | AvgLatency |
| :----------- | :------- | --------: | ---------: |
| Agentic RAG  | 4/6      |      5785 |     43.724 |
| Hybrid RAG   | 4/6      |      4072 |      30.31 |
| Naive RAG    | 4/6      |      5024 |      29.92 |

git 

### what we selected and why:

Although all three retrieval architectures achieved the same accuracy (4/6) on our evaluation set, we selected **Hybrid RAG** as the final retrieval architecture.

Hybrid RAG achieved the same retrieval accuracy as Naive RAG while requiring fewer tokens per query (4072 vs. 5024), making it more cost-efficient. It also retrieved fewer documents on average due to metadata filtering and keyword search, resulting in more focused context without sacrificing answer quality. Although its average latency (30.31 s) was slightly higher than Naive RAG (29.92 s), the difference was negligible compared to the reduction in token usage.

Agentic RAG introduced iterative retrieval and query refinement, but on our banking policy dataset it did not improve accuracy. Instead, it consumed the largest number of tokens (5785) and had the highest latency (43.72 s). Since the additional reasoning steps did not provide measurable gains on our evaluation set, its extra computational cost was not justified.

Therefore, **Hybrid RAG** provides the best balance between retrieval quality, efficiency, and computational cost, making it the most suitable architecture for deployment in our banking compliance assistant.
