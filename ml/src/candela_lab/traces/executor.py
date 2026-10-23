import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from candela_lab import config
from candela_lab.paths import CONTRACTS_DIR
from candela_lab.traces import market
from candela_lab.traces.schema import validate_arguments


@dataclass
class ToolResult:
    model_view: str
    ui_view: dict[str, Any] | None = None

    @property
    def parsed(self) -> dict[str, Any]:
        return json.loads(self.model_view)

    @property
    def is_error(self) -> bool:
        return '"error"' in self.model_view[:20]


class Executor(Protocol):
    name: str

    def execute(self, tool: str, arguments: dict[str, Any]) -> ToolResult: ...


def error_view(code: str, message: str) -> ToolResult:
    return ToolResult(market.dumps({"error": code, "message": message}))


def contract_examples() -> dict[str, str]:
    text = (CONTRACTS_DIR / "tools.md").read_text()
    out: dict[str, str] = {}
    for section in re.split(r"^## ", text, flags=re.M)[1:]:
        name = section.split("\n", 1)[0].strip()
        if inline := re.search(r"Model view: `(\{.*?\})`", section):
            out[name] = json.dumps(json.loads(inline.group(1)), separators=(",", ":"), ensure_ascii=False)
        elif block := re.search(r"Model view:\s*```json\s*(\{.*?\})\s*```", section, re.S):
            out[name] = json.dumps(json.loads(block.group(1)), separators=(",", ":"), ensure_ascii=False)
    return out


@dataclass
class FakeExecutor:
    """Serves the contract examples verbatim for their own arguments and synthetic, contract-shaped views otherwise."""

    as_of: str
    fundamentals_available: float = 0.5
    serve_contract_examples: bool = False
    name: str = "fake"
    failures: dict[tuple[str, str], str] = field(default_factory=dict)
    _market: market.SyntheticMarket | None = None

    def __post_init__(self) -> None:
        self._market = market.SyntheticMarket(self.as_of)
        self._examples = contract_examples()
        self._schemas = {t["function"]["name"]: t["function"]["parameters"] for t in config.tools_schema()}

    def fundamentals_enabled(self, symbol: str) -> bool:
        h = int.from_bytes(symbol.encode(), "little") % 100
        return h < self.fundamentals_available * 100

    def _contract_example(self, tool: str, arguments: dict[str, Any]) -> str | None:
        expected = CONTRACT_ARGS.get(tool)
        if not self.serve_contract_examples or expected is None or tool not in self._examples:
            return None
        defaults = {"get_technical_indicators": {"range": "1Y"}, "get_fundamentals": {"period": "annual"}}
        normalized = {
            k: v for k, v in arguments.items() if defaults.get(tool, {}).get(k) != v and k != "limit"
        }
        return self._examples[tool] if normalized == expected else None

    def execute(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        if tool not in self._schemas:
            return error_view("invalid_arguments", f"unknown tool {tool}")
        problems = validate_arguments(self._schemas[tool], arguments)
        if problems:
            return error_view("invalid_arguments", problems[0])
        m = self._market
        assert m is not None
        if tool == "search_symbols":
            query = arguments["query"]
            if query == "nvidia" and self.serve_contract_examples:
                return ToolResult(self._examples["search_symbols"])
            return ToolResult(market.dumps(m.search(query, int(arguments.get("limit", 5)))))
        symbol = arguments["symbol"]
        example = self._contract_example(tool, arguments)
        if example:
            return ToolResult(example)
        forced = self.failures.get((tool, symbol))
        if forced:
            return error_view(forced, _failure_message(forced, symbol))
        if not m.known(symbol):
            return error_view("not_found", f"unknown symbol {symbol}")
        match tool:
            case "get_quote":
                return ToolResult(market.dumps(m.quote(symbol)))
            case "get_price_history":
                return ToolResult(market.dumps(m.history(symbol, arguments.get("range", "1Y"))))
            case "get_technical_indicators":
                return ToolResult(market.dumps(m.indicators(symbol, arguments.get("range", "1Y"))))
            case "get_forecast":
                return ToolResult(market.dumps(m.forecast(symbol)))
            case "get_fundamentals":
                if symbol in market.ETF:
                    return error_view("data_unavailable", f"no SEC financial statements for fund {symbol}")
                if not self.fundamentals_enabled(symbol):
                    return error_view("data_unavailable", "SEC fundamentals provider is not configured")
                view = m.fundamentals(
                    symbol, arguments.get("period", "annual"), int(arguments.get("limit", 4))
                )
                return ToolResult(market.dumps(view))
        return error_view("invalid_arguments", f"unsupported tool {tool}")


CONTRACT_ARGS = {
    "get_quote": {"symbol": "NVDA"},
    "get_price_history": {"symbol": "NVDA", "range": "6M"},
    "get_technical_indicators": {"symbol": "NVDA"},
    "get_fundamentals": {"symbol": "AAPL"},
    "get_forecast": {"symbol": "NVDA"},
}


def _failure_message(code: str, symbol: str) -> str:
    return {
        "data_unavailable": f"price data for {symbol} is temporarily unavailable",
        "not_found": f"unknown symbol {symbol}",
    }.get(code, "tool failed")


@dataclass
class GatewayExecutor:
    base_url: str = "http://127.0.0.1:8739"
    timeout: float = 10.0
    name: str = "gateway"
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def health(self) -> bool:
        assert self._client is not None
        try:
            r = self._client.post(
                "/internal/v1/tools/execute",
                json={"name": "search_symbols", "arguments": {"query": "nvidia"}},
            )
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    def execute(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        assert self._client is not None
        r = self._client.post("/internal/v1/tools/execute", json={"name": tool, "arguments": arguments})
        if r.status_code >= 500:
            r.raise_for_status()
        body = r.json()
        if "modelView" not in body:
            return error_view("invalid_arguments", str(body.get("message") or body)[:200])
        return ToolResult(body["modelView"], body.get("uiView"))


def _key_paths(obj: Any, prefix: str = "") -> list[str]:
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            out.append(prefix + k)
            out.extend(_key_paths(v, prefix + k + "."))
        return out
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return _key_paths(obj[0], prefix + "[]")
    return []


def check_contract_shapes(as_of: str) -> list[str]:
    """Compare key order of synthetic views with the contract examples; returns mismatches."""
    examples = contract_examples()
    fake = FakeExecutor(as_of=as_of, fundamentals_available=1.0)
    calls = {
        "search_symbols": {"query": "apple"},
        "get_quote": {"symbol": "MSFT"},
        "get_price_history": {"symbol": "MSFT", "range": "6M"},
        "get_technical_indicators": {"symbol": "MSFT"},
        "get_fundamentals": {"symbol": "MSFT"},
        "get_forecast": {"symbol": "MSFT"},
    }
    problems = []
    for tool, args in calls.items():
        want = [p for p in _key_paths(json.loads(examples[tool])) if not p.startswith("signals.")]
        got = [p for p in _key_paths(fake.execute(tool, args).parsed) if not p.startswith("signals.")]
        if [p for p in got if p in want] != want:
            problems.append(f"{tool}: expected keys {want}, got {got}")
    return problems
