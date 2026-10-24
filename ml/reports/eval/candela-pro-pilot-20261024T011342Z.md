# Evaluation — candela-pro-pilot

- Model: `gemma-4-12b-qat` (base `google/gemma-4-12B-it-qat-q4_0-unquantized`), adapter `runs/pilot-candela-pro/adapter`
- Mode: fast, dataset d0.1, eval seed 1234, greedy decoding, thinking off
- Evaluated 2026-10-24T01:13:42+00:00 on Apple M5 Pro · arm64 in 47.1 min, peak MLX memory 13.04 GB

| Suite | Metric | Value | n | Seconds | Details |
|---|---|---:|---:|---:|---|
| Financial PhraseBank (`fpb`) | macro_f1 | 0.789 | 300 | 48.9 | f1=0.789, accuracy=0.807, unparsed=0.000 |
| FiQA sentiment (`fiqa_sa`) | weighted_f1 | 0.697 | 235 | 31.6 | f1=0.697, accuracy=0.621, unparsed=0.000 |
| Gold headlines (`headlines`) | weighted_f1 | 0.752 | 300 | 44.8 | f1=0.752, accuracy=0.760, unparsed=0.000 |
| FinQA (`finqa`) | numeric_em | 0.590 | 100 | 284.6 | unparsed=0.000 |
| ConvFinQA (`convfinqa`) | numeric_em | 0.720 | 100 | 456.5 | unparsed=0.000 |
| TAT-QA (arithmetic) (`tatqa`) | numeric_em | 0.850 | 100 | 420.1 | unparsed=0.000 |
| Candela tool use (`tool_use`) | tool_choice_f1 | 0.871 | 40 | 1384.6 | toolChoicePrecision=0.865, toolChoiceRecall=0.878, toolChoiceF1=0.871, argumentValidity=1.000, malformedCalls=0, noToolAccuracy=1.000, groundingRate=0.981, callTurns=53, answerTurns=52 |
| Held-out loss (d0.1 valid) (`heldout_loss`) | loss | 0.510 | 88 | 149.8 | tokens=14666 |

## Samples

**fpb** — `{"prompt": " the following financial text. Reply with exactly one word: positive, negative or neutral.\n\nText: ( ADP News ) - Finnish handling systems provider Cargotec Oyj ( HEL : CGCBV ) announced on Friday it won orders worth EUR 10 million ( USD 13.2 m ) to deliver linkspans to Jordan , Morocco and Ireland .", "output": "positive", "gold": "positive", "pred": "positive"}`

**fpb** — `{"prompt": "word: positive, negative or neutral.\n\nText: The world 's biggest magazine paper maker said the program to improve efficiency will include closing several of its least competitive mills and would cover all the company 's operations resulting in annual savings of some euro200 million US$ 240 million .", "output": "Neutral", "gold": "positive", "pred": "neutral"}`

**fiqa_sa** — `{"prompt": "Classify the sentiment of the following financial text. Reply with exactly one word: positive, negative or neutral.\n\nText: $BBRY Actually lost .03c per share if U incl VZ as no debt and 3.1 in Cash.", "output": "Neutral", "gold": "negative", "pred": "neutral"}`

**fiqa_sa** — `{"prompt": "Classify the sentiment of the following financial text. Reply with exactly one word: positive, negative or neutral.\n\nText: Legal & General share price: Finance chief to step down", "output": "Neutral", "gold": "negative", "pred": "neutral"}`

**headlines** — `{"prompt": "Look for indications that the price of gold is increasing.. Is there a mention of a Direction Up in relation to gold in the news headline? Please answer with Yes or No.\nText: Gold climbs to 2-1/2 week highs on views Fed will hold off on rates\n\nReply with exactly one word: Yes or No.", "output": "Yes", "gold": "yes", "pred": "yes"}`

**headlines** — `{"prompt": "Consider whether the headline mentions the price of gold.. Is the news headline discussing a Price or Not related to gold? Please respond with Yes or No.\nText: gold monetisation scheme to be revamped this week: report\n\nReply with exactly one word: Yes or No.", "output": "No", "gold": "no", "pred": "no"}`

**finqa** — `{"prompt": ", and were reflected as an increase to common stock in the consolidated statements of shareholders 2019 equity. .\n\nQuestion: what was the greatest provision for income taxes , in millions?\n\nShow the calculation in at most two short lines, then finish with a final line of the form 'Answer: <number>'.", "output": "829 \u2212 419 = 410\n\nAnswer: 410", "gold": "829.0", "pred": 410.0, "ok": false}`

**finqa** — `{"prompt": "es of company stock. .\n\nQuestion: assuming the same level of settlements as in fiscal 2007 , what would be the ending balance at march 31 2008 in millions for unrecognized tax benefits?\\\\n\n\nShow the calculation in at most two short lines, then finish with a final line of the form 'Answer: <number>'.", "output": "224 - 56 = 168\nAnswer: 168", "gold": "112.0", "pred": 168.0, "ok": false}`

**convfinqa** — `{"prompt": " pacific . this business provides card payment processing services to merchants in the asia-pacific region . the .\nConversations: \nq0: what is the value of goodwill? {answer0}\nQuestion: what is the value of customer-related intangible assets?\n\nFinish with a final line of the form 'Answer: <number>'.", "output": "4,091 thousand.\n\n**Answer: 4,091 thousand**", "gold": "4091.0", "pred": 4091.0, "ok": true}`

**convfinqa** — `{"prompt": "es card payment processing services to merchants in the asia-pacific region . the .\nConversations: \nq0: what is the value of goodwill? {answer0}\nq1: what is the value of customer-related intangible assets? {answer1}\nQuestion: what is the sum?\n\nFinish with a final line of the form 'Answer: <number>'.", "output": "13,536 + 4,091 = 17,627.\n\n**Answer: 17,627**", "gold": "17627.0", "pred": 17627.0, "ok": true}`

**tatqa** — `{"prompt": "1,252 |\n| Other | 61,908 | 46,616 | 15,292 |\n| Total | $880,737 | $756,529 | $124,208 |\n\nQuestion: What is the change in Personnel costs, including teammate benefits between 2018 and 2019?\n\nShow the calculation in at most two short lines, then finish with a final line of the form 'Answer: <number>'.", "output": "684,837 - 593,955 = 90,882\nAnswer: 90,882", "gold": "90882", "pred": 90882.0, "ok": true}`

**tatqa** — `{"prompt": "otes receivable and other non-current assets | $406.4 | $962.6 |\n\nQuestion: What was long-term prepaid ground rent as a percentage of notes receivable and other non-current assets in 2018?\n\nShow the calculation in at most two short lines, then finish with a final line of the form 'Answer: <number>'.", "output": "607.5 \u00f7 962.6 = 0.631\n\nAnswer: 63.1%", "gold": "63.11", "pred": 63.1, "ok": true}`

**tool_use** — `{"gold": ["get_technical_indicators"], "pred": ["get_technical_indicators"], "output": "<|tool_call>call:get_technical_indicators{symbol:<|\"|>COST<|\"|>}<tool_call|>"}`

**tool_use** — `{"gold": ["get_technical_indicators"], "pred": ["get_technical_indicators"], "output": "<|tool_call>call:get_technical_indicators{symbol:<|\"|>CAT<|\"|>}<tool_call|>"}`

