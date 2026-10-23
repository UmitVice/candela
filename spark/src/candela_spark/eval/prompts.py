SAMPLE_PROMPTS = [
    "The water cycle describes how",
    "In the early nineteenth century, the city of London",
    "Photosynthesis is the process by which",
    "The company reported that revenue for the fiscal year",
    "When the Federal Reserve raises interest rates,",
    "Risk factors that could affect our business include",
    "A bond is a debt security in which",
    "Inflation is measured by",
]

# (context, correct continuation, distractors): scored by total log-likelihood of each continuation.
FINANCE_CLOZE: list[tuple[str, str, list[str]]] = [
    (
        "When a central bank raises interest rates, borrowing becomes more",
        " expensive",
        [" fun", " colorful", " silent"],
    ),
    ("A company's revenue minus its expenses is its", " profit", [" weather", " height", " color"]),
    ("Shareholders may receive a portion of profits as a", " dividend", [" vacation", " recipe", " melody"]),
    (
        "The balance sheet lists a company's assets, liabilities and shareholders'",
        " equity",
        [" hobbies", " pets", " songs"],
    ),
    (
        "A general rise in prices over time is called",
        " inflation",
        [" gravity", " erosion", " photosynthesis"],
    ),
    ("Investors who expect a stock to fall may sell it", " short", [" green", " loudly", " upstairs"]),
    (
        "Gross domestic product measures the total value of goods and services",
        " produced",
        [" painted", " sung", " slept"],
    ),
    ("Bond prices usually fall when interest rates", " rise", [" sing", " sleep", " melt"]),
    ("The annual report filed with the SEC is known as Form", " 10-K", [" banana", " blue", " river"]),
    ("Diversification helps investors reduce", " risk", [" rain", " hunger", " noise"]),
    (
        "Net income divided by the number of shares outstanding gives earnings per",
        " share",
        [" tree", " song", " cloud"],
    ),
    (
        "A recession is commonly defined as two consecutive quarters of negative economic",
        " growth",
        [" music", " weather", " poetry"],
    ),
    (
        "Cash flow from operating activities shows how much cash a company generates from its core",
        " business",
        [" garden", " dreams", " ocean"],
    ),
    (
        "Our results of operations could be adversely affected by changes in foreign currency exchange",
        " rates",
        [" birds", " colors", " flowers"],
    ),
    ("The Federal Reserve is the central bank of the United", " States", [" Nations", " Kingdom", " Colors"]),
    ("A loan that is secured by real estate is called a", " mortgage", [" melody", " sandwich", " planet"]),
    (
        "Companies listed on a stock exchange are said to be publicly",
        " traded",
        [" painted", " cooked", " frozen"],
    ),
    ("When demand exceeds supply, prices tend to", " increase", [" whisper", " swim", " vanish"]),
    (
        "The ratio of a company's share price to its earnings per share is the price-to-earnings",
        " ratio",
        [" song", " river", " forest"],
    ),
    (
        "Management's discussion and analysis of financial condition and results of",
        " operations",
        [" gardening", " poetry", " sleep"],
    ),
    (
        "An increase in unemployment usually reduces consumer",
        " spending",
        [" singing", " sleeping", " flying"],
    ),
    (
        "Treasury bills are short-term debt obligations issued by the U.S.",
        " government",
        [" orchestra", " zoo", " bakery"],
    ),
    (
        "The interest rate at which banks lend to each other overnight is the federal funds",
        " rate",
        [" tree", " song", " meal"],
    ),
    (
        "A portfolio that holds many different assets is well",
        " diversified",
        [" painted", " cooked", " frozen"],
    ),
]

ATTENTION_SENTENCES = [
    "The Federal Reserve raised interest rates to fight inflation.",
    "Apple reported record revenue of 394 billion dollars.",
    "Higher bond yields pushed stock prices lower this week.",
    "The company cut its dividend after earnings fell sharply.",
    "Risk factors include competition, regulation and currency changes.",
    "Investors sold shares when the bank announced large losses.",
    "Net income rose 12 percent while operating expenses declined.",
    "A recession lowers demand, profits and employment across the economy.",
]
