package market

import (
	"errors"
	"regexp"
)

var (
	ErrNotFound    = errors.New("not_found")
	ErrUnavailable = errors.New("data_unavailable")
	ErrInvalid     = errors.New("invalid_arguments")
)

var symbolRE = regexp.MustCompile(`^[A-Z][A-Z0-9.\-]{0,9}$`)

func ValidSymbol(s string) bool { return symbolRE.MatchString(s) }

type SymbolInfo struct {
	Symbol   string `json:"symbol"`
	Name     string `json:"name"`
	Exchange string `json:"exchange"`
}

type Bar struct {
	T string  `json:"t"`
	O float64 `json:"o"`
	H float64 `json:"h"`
	L float64 `json:"l"`
	C float64 `json:"c"`
	V float64 `json:"v"`
}

type Quote struct {
	Symbol           string  `json:"symbol"`
	Name             string  `json:"name"`
	Exchange         string  `json:"exchange"`
	Currency         string  `json:"currency"`
	AsOf             string  `json:"asOf"`
	Close            float64 `json:"close"`
	PreviousClose    float64 `json:"previousClose"`
	Change           float64 `json:"change"`
	ChangePct        float64 `json:"changePct"`
	Open             float64 `json:"open"`
	High             float64 `json:"high"`
	Low              float64 `json:"low"`
	Volume           float64 `json:"volume"`
	FiftyTwoWeekHigh float64 `json:"fiftyTwoWeekHigh"`
	FiftyTwoWeekLow  float64 `json:"fiftyTwoWeekLow"`
	AvgVolume30d     float64 `json:"avgVolume30d"`
	Source           string  `json:"source"`
	Delayed          bool    `json:"delayed"`
}

type PriceHistory struct {
	Symbol   string `json:"symbol"`
	Range    string `json:"range"`
	Interval string `json:"interval"`
	Bars     []Bar  `json:"bars"`
	Source   string `json:"source"`
	AsOf     string `json:"asOf"`
}

type IndicatorPoint struct {
	T          string   `json:"t"`
	SMA20      *float64 `json:"sma20,omitempty"`
	SMA50      *float64 `json:"sma50,omitempty"`
	SMA200     *float64 `json:"sma200,omitempty"`
	EMA12      *float64 `json:"ema12,omitempty"`
	EMA26      *float64 `json:"ema26,omitempty"`
	RSI14      *float64 `json:"rsi14,omitempty"`
	MACD       *float64 `json:"macd,omitempty"`
	MACDSignal *float64 `json:"macdSignal,omitempty"`
	MACDHist   *float64 `json:"macdHist,omitempty"`
	BBUpper    *float64 `json:"bbUpper,omitempty"`
	BBMiddle   *float64 `json:"bbMiddle,omitempty"`
	BBLower    *float64 `json:"bbLower,omitempty"`
	ATR14      *float64 `json:"atr14,omitempty"`
}

type LatestIndicators struct {
	IndicatorPoint
	Close float64 `json:"close"`
}

type Signal struct {
	ID     string `json:"id"`
	Label  string `json:"label"`
	Tone   string `json:"tone"`
	Detail string `json:"detail"`
}

type IndicatorSet struct {
	Symbol  string           `json:"symbol"`
	Range   string           `json:"range"`
	AsOf    string           `json:"asOf"`
	Latest  LatestIndicators `json:"latest"`
	Series  []IndicatorPoint `json:"series"`
	Signals []Signal         `json:"signals"`
}

type FundamentalPeriod struct {
	FiscalYear         int      `json:"fiscalYear"`
	FiscalPeriod       string   `json:"fiscalPeriod"`
	PeriodEnd          string   `json:"periodEnd"`
	Revenue            *float64 `json:"revenue,omitempty"`
	GrossProfit        *float64 `json:"grossProfit,omitempty"`
	OperatingIncome    *float64 `json:"operatingIncome,omitempty"`
	NetIncome          *float64 `json:"netIncome,omitempty"`
	EPSDiluted         *float64 `json:"epsDiluted,omitempty"`
	OperatingCashFlow  *float64 `json:"operatingCashFlow,omitempty"`
	CapitalExpenditure *float64 `json:"capitalExpenditure,omitempty"`
	FreeCashFlow       *float64 `json:"freeCashFlow,omitempty"`
	TotalAssets        *float64 `json:"totalAssets,omitempty"`
	TotalLiabilities   *float64 `json:"totalLiabilities,omitempty"`
	CashAndEquivalents *float64 `json:"cashAndEquivalents,omitempty"`
	LongTermDebt       *float64 `json:"longTermDebt,omitempty"`
	SharesOutstanding  *float64 `json:"sharesOutstanding,omitempty"`
}

type Ratios struct {
	GrossMarginPct     *float64 `json:"grossMarginPct,omitempty"`
	OperatingMarginPct *float64 `json:"operatingMarginPct,omitempty"`
	NetMarginPct       *float64 `json:"netMarginPct,omitempty"`
	FCFMarginPct       *float64 `json:"fcfMarginPct,omitempty"`
	RevenueGrowthPct   *float64 `json:"revenueGrowthPct,omitempty"`
	EPSGrowthPct       *float64 `json:"epsGrowthPct,omitempty"`
	DebtToAssets       *float64 `json:"debtToAssets,omitempty"`
}

type Fundamentals struct {
	Symbol   string              `json:"symbol"`
	Name     string              `json:"name"`
	Period   string              `json:"period"`
	Currency string              `json:"currency"`
	Periods  []FundamentalPeriod `json:"periods"`
	Ratios   Ratios              `json:"ratios"`
	Source   string              `json:"source"`
	AsOf     string              `json:"asOf"`
}

type Horizon struct {
	Months     int     `json:"months"`
	TargetDate string  `json:"targetDate"`
	P10        float64 `json:"p10"`
	P50        float64 `json:"p50"`
	P90        float64 `json:"p90"`
}

type Forecast struct {
	Symbol     string    `json:"symbol"`
	AsOf       string    `json:"asOf"`
	BasePrice  float64   `json:"basePrice"`
	Source     string    `json:"source"`
	Method     string    `json:"method"`
	Horizons   []Horizon `json:"horizons"`
	Disclaimer string    `json:"disclaimer"`
}

type ProviderStatus struct {
	ID     string `json:"id"`
	Status string `json:"status"`
	AsOf   string `json:"asOf,omitempty"`
}
