# Evaluation — spark-35m-m1

Checkpoint `step-00004400` of run `spark-35m-m1`: step 4,400, 144,179,200 tokens. Evaluated 2026-10-23T10:19:14Z.

## Validation loss per source (nats/token, 64 × 1024-token windows)

| Source | bf16 | int4 (QAT forward) | int4 export | ppl bf16 | ppl int4 |
|---|---|---|---|---|---|
| cosmopedia-v2 | 3.2586 | 3.2617 | 3.2619 | 26.01 | 26.09 |
| edgar | 2.3583 | 2.3619 | 2.3619 | 10.57 | 10.61 |
| finemath | 2.9665 | 2.9694 | 2.9690 | 19.42 | 19.48 |
| fineweb-edu | 3.7548 | 3.7580 | 3.7579 | 42.72 | 42.86 |
| fineweb-edu-dedup | 3.5944 | 3.5937 | 3.5937 | 36.4 | 36.37 |
| fineweb-edu-finance | 3.4426 | 3.4453 | 3.4452 | 31.27 | 31.35 |
| wikipedia-en | 3.4882 | 3.4936 | 3.4936 | 32.73 | 32.9 |

Mean bf16 3.2662, mean int4 3.2691, relative int4 gap +0.088 %.

## Zero-shot suite

| Suite | Metric | n | Score | Chance |
|---|---|---|---|---|
| lambada | acc | 500 | 0.138 | 0.00 |
| arc-easy | acc_norm | 500 | 0.352 | 0.25 |
| hellaswag | acc_norm | 500 | 0.278 | 0.25 |
| piqa | acc_norm | 500 | 0.582 | 0.50 |
| blimp | acc | 1000 | 0.869 | 0.50 |
| finance-cloze | acc | 24 | 1.000 | 0.25 |
| finance-cloze-hard | acc | 16 | 0.812 | 0.25 |

## Fixed-seed samples (int4, temperature 0.7, seed 0)

**The water cycle describes how** a person reacts with water to prevent an injury. It is usually a short walk or a short walk. The water cycle is a short walk or short walk and the water cycle is a short walk or short walk. It is usually done in the form of a stream or stream or stream. It can

**In the early nineteenth century, the city of London**, where many of the most famous writers and writers were from the English-speaking world, had quite a well-known and unique character. The earlier census, an annual census, was a large and complex affair with the great master of the English language. In the nineteenth century, the Roman Empire lost a significant

**Photosynthesis is the process by which** light forms, and the process is conducted to produce the desired effects, and, in some cases, the process is performed. The process is a process of photosynthesis and the process is performed by a photosynthesis process. The photosynthesis process is done by a photosynthesis process.

**The company reported that revenue for the fiscal year** ended May 28, 2018, as a result of the COVID-19 pandemic, is expected to continue to be a new revenue source for fiscal year 2020. The Company’s revenue for fiscal year 2020 was $189 million

**When the Federal Reserve raises interest rates,** the economy will have to be changed as the Federal Reserve needs to increase its assets. The financial sector is also affected by the federal government’s initiatives, including investments in private and public funds, which are not the primary source of funding. The stock market is affected by the federal government’s decision to increase

**Risk factors that could affect our business include**: credit card, credit card market, disability, community, community, and many others. People with that risk can be affected by a variety of factors, including the nature of their financial situation, the financial condition of the individual, and the likelihood that they will receive the financial, credit, or financial

**A bond is a debt security in which** an employee’s bond is made up of two or more fibers or fibers. The bond is generally made up of two or more fibers, or fibers. The bond’s bond’s bond’s bond size is usually small and has a lower resistance to blockage. This makes it difficult for a person to buy

**Inflation is measured by** measuring the quantity of goods and services a business has. It is measured by measuring the quantity of goods and services a business has. It is measured by measuring the quantity of goods and services a business has.
The rate of inflation is calculated by measuring the quantity of goods and services a business has.
The

