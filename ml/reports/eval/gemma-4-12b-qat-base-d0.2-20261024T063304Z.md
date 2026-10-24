# Evaluation — gemma-4-12b-qat-base-d0.2

- Model: `gemma-4-12b-qat` (base `google/gemma-4-12B-it-qat-q4_0-unquantized`)
- Mode: fast, dataset d0.2, eval seed 1234, greedy decoding, thinking off
- Evaluated 2026-10-24T06:33:04+00:00 on Apple M5 Pro · arm64 in 44.1 min, peak MLX memory 10.95 GB

| Suite | Metric | Value | n | Seconds | Details |
|---|---|---:|---:|---:|---|
| Financial PhraseBank (`fpb`) | macro_f1 | 0.855 | 300 | 51.2 | f1=0.855, accuracy=0.857, unparsed=0.000 |
| FiQA sentiment (`fiqa_sa`) | weighted_f1 | 0.757 | 235 | 36.1 | f1=0.757, accuracy=0.706, unparsed=0.000 |
| Gold headlines (`headlines`) | weighted_f1 | 0.750 | 300 | 50.4 | f1=0.750, accuracy=0.757, unparsed=0.000 |
| FinQA (`finqa`) | numeric_em | 0.660 | 100 | 295.7 | unparsed=0.000 |
| ConvFinQA (`convfinqa`) | numeric_em | 0.260 | 100 | 439.5 | unparsed=0.000 |
| TAT-QA (arithmetic) (`tatqa`) | numeric_em | 0.880 | 100 | 180.2 | unparsed=0.000 |
| FinanceBench (evidence given) (`financebench`) | accuracy | 0.770 | 126 | 415.0 | items=150, unscorable=24 |
| IFEval (strict, prompt level) (`ifeval`) | prompt_strict | 0.860 | 150 | 584.7 | instructionStrict=0.891, truncated=0.060 |
| Candela tool use (`tool_use`) | tool_choice_f1 | 0.717 | 40 | 585.4 | toolChoicePrecision=0.732, toolChoiceRecall=0.703, toolChoiceF1=0.717, argumentValidity=1.000, malformedCalls=0, noToolAccuracy=1.000, groundingRate=0.939, callTurns=50, answerTurns=49 |

## Samples

**fpb** — `{"prompt": " the following financial text. Reply with exactly one word: positive, negative or neutral.\n\nText: ( ADP News ) - Finnish handling systems provider Cargotec Oyj ( HEL : CGCBV ) announced on Friday it won orders worth EUR 10 million ( USD 13.2 m ) to deliver linkspans to Jordan , Morocco and Ireland .", "output": "positive", "gold": "positive", "pred": "positive"}`

**fpb** — `{"prompt": "word: positive, negative or neutral.\n\nText: The world 's biggest magazine paper maker said the program to improve efficiency will include closing several of its least competitive mills and would cover all the company 's operations resulting in annual savings of some euro200 million US$ 240 million .", "output": "positive", "gold": "positive", "pred": "positive"}`

**fiqa_sa** — `{"prompt": "Classify the sentiment of the following financial text. Reply with exactly one word: positive, negative or neutral.\n\nText: $BBRY Actually lost .03c per share if U incl VZ as no debt and 3.1 in Cash.", "output": "negative", "gold": "negative", "pred": "negative"}`

**fiqa_sa** — `{"prompt": "Classify the sentiment of the following financial text. Reply with exactly one word: positive, negative or neutral.\n\nText: Legal & General share price: Finance chief to step down", "output": "negative", "gold": "negative", "pred": "negative"}`

**headlines** — `{"prompt": "Look for indications that the price of gold is increasing.. Is there a mention of a Direction Up in relation to gold in the news headline? Please answer with Yes or No.\nText: Gold climbs to 2-1/2 week highs on views Fed will hold off on rates\n\nReply with exactly one word: Yes or No.", "output": "Yes", "gold": "yes", "pred": "yes"}`

**headlines** — `{"prompt": "Consider whether the headline mentions the price of gold.. Is the news headline discussing a Price or Not related to gold? Please respond with Yes or No.\nText: gold monetisation scheme to be revamped this week: report\n\nReply with exactly one word: Yes or No.", "output": "No", "gold": "no", "pred": "no"}`

**finqa** — `{"prompt": ", and were reflected as an increase to common stock in the consolidated statements of shareholders 2019 equity. .\n\nQuestion: what was the greatest provision for income taxes , in millions?\n\nShow the calculation in at most two short lines, then finish with a final line of the form 'Answer: <number>'.", "output": "To find the greatest provision for income taxes, we compare the \"provision for income taxes\" row for the years 2006, 2005, and 2004:\n2006: $829 million; 2005: $480 million; 2004: $104 million.\n\nAnswer: 829", "gold": "829.0", "pred": 829.0, "ok": true}`

**finqa** — `{"prompt": "es of company stock. .\n\nQuestion: assuming the same level of settlements as in fiscal 2007 , what would be the ending balance at march 31 2008 in millions for unrecognized tax benefits?\\\\n\n\nShow the calculation in at most two short lines, then finish with a final line of the form 'Answer: <number>'.", "output": "To calculate the ending balance at March 31, 2008, in millions:\n$224 (April 1, 2007 balance) - $56 (reductions) = $168 (in thousands)\n$168 / 1,000 = $0.168 million\n\nAnswer: 0.168", "gold": "112.0", "pred": 0.168, "ok": false}`

**convfinqa** — `{"prompt": " pacific . this business provides card payment processing services to merchants in the asia-pacific region . the .\nConversations: \nq0: what is the value of goodwill? {answer0}\nQuestion: what is the value of customer-related intangible assets?\n\nFinish with a final line of the form 'Answer: <number>'.", "output": "the fiscal 2008 business acquisitions.\n\nThe table lists the following items (in thousands):\n1. Goodwill: $13,536\n2. **Customer-related intangible assets: $4,091**\n3. Contract-based intangible assets: $1,031\n4. Property and equipment: $267\n5. Other current assets`

**convfinqa** — `{"prompt": "es card payment processing services to merchants in the asia-pacific region . the .\nConversations: \nq0: what is the value of goodwill? {answer0}\nq1: what is the value of customer-related intangible assets? {answer1}\nQuestion: what is the sum?\n\nFinish with a final line of the form 'Answer: <number>'.", "output": "able provided in the context, row 2 shows \"goodwill\" with a total value of $13,536 (in thousands).\n2.  **Value of customer-related intangible assets (from q1):** Looking at the table provided in the context, row 3 shows \"customer-related intangible assets\" with a`

**tatqa** — `{"prompt": "1,252 |\n| Other | 61,908 | 46,616 | 15,292 |\n| Total | $880,737 | $756,529 | $124,208 |\n\nQuestion: What is the change in Personnel costs, including teammate benefits between 2018 and 2019?\n\nShow the calculation in at most two short lines, then finish with a final line of the form 'Answer: <number>'.", "output": "$684,837 (2019) - $593,955 (2018) = $90,882\nAnswer: $90,882", "gold": "90882", "pred": 90882.0, "ok": true}`

**tatqa** — `{"prompt": "otes receivable and other non-current assets | $406.4 | $962.6 |\n\nQuestion: What was long-term prepaid ground rent as a percentage of notes receivable and other non-current assets in 2018?\n\nShow the calculation in at most two short lines, then finish with a final line of the form 'Answer: <number>'.", "output": "Calculation: ($607.5 / $962.6) * 100\nAnswer: 63.12%", "gold": "63.11", "pred": 63.12, "ok": true}`

**financebench** — `{"question": "atements are an integral part of this statement.\n \n60\n\nQuestion: What is the FY2018 capital expenditure amount (in USD millions) for 3M? Give a response to the question by relying on the details shown in the cash flow statement.\n\nAnswer in at most three sentences and state the key figure explicitly.", "output": "The FY2018 capital expenditure amount for 3M is $1,577 million. This figure is listed under the \"Cash Flows from Investing Activities\" section as \"Purchases of property, plant and equipment (PP&E).\"", "gold": "$1577.00", "ok": true}`

**financebench** — `{"question": ".\n58\n\nQuestion: Assume that you are a public equities analyst. Answer the following question by primarily using information that is shown in the balance sheet: what is the year end FY2018 net PPNE for 3M? Answer in USD billions.\n\nAnswer in at most three sentences and state the key figure explicitly.", "output": "The year-end FY2018 net Property, Plant and Equipment (PPNE) for 3M is $8.738 billion. This figure is derived from the \"Property, plant and equipment net\" line item in the Consolidated Balance Sheet, which shows $8,738 million for the year ended December 31, 2018."`

**ifeval** — `{"prompt": "Write a resume for a fresh high school graduate who is seeking their first job. Make sure to include at least 12 placeholder represented by square brackets, such as [address], [name].", "output": "**[Full Name]**\n[Address] | [Phone Number] | [Email Address]\n[LinkedIn Profile URL (Optional)]\n\n**OBJECTIVE**\nMotivated and reliable high school graduate with a strong academic record and a passion for [Specific Industry/Field, e.g., Customer Service/Retail/Technology]. Seeking an entry-level position at [Company Name] to leverage my [Skill 1] and [Skill 2] to contribute to team succ`

**ifeval** — `{"prompt": "Write an email to my boss telling him that I am quitting. The email must contain a title wrapped in double angular brackets, i.e. <<title>>.\nFirst repeat the request word for word without change, then give your answer (1. do not say any words or characters before repeating the request; 2. the reques", "output": "Write an email to my boss telling him that I am quitting. The email must contain a title wrapped in double angular brackets, i.e. <<title>>.\n\nSubject: Resignation - [Your Name]\n\n<<Resignation Notice>>\n\nDear [Boss's Name],\n\nPlease accept this email as formal notific`

**tool_use** — `{"gold": ["search_symbols"], "pred": ["search_symbols"], "output": "<|tool_call>call:search_symbols{query:<|\"|>Microchip Technology<|\"|>}<tool_call|>"}`

**tool_use** — `{"gold": ["get_quote", "get_price_history", "get_technical_indicators", "get_fundamentals", "get_forecast"], "pred": ["get_quote", "get_price_history", "get_technical_indicators", "get_fundamentals", "get_forecast"], "output": "<|tool_call>call:get_quote{symbol:<|\"|>CAT<|\"|>}<tool_call|><|tool_call>call:get_price_history{range:<|\"|>1Y<|\"|>,symbol:<|\"|>CAT<|\"|>}<tool_call|><|tool_call>call:get_technical_indicators{range:<|\"|>1Y<|\"|>,symbol:<|\"|>CAT<|\"|>}<tool_call|><|tool_call>call:get_fundamentals{period:<|\"|>annual<|\"|>,symbol:<|\"|>CAT<|\"|>}<tool_call|><|tool_call>call:get_forec`

